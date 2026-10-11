"""LangGraph node: decides whether the Supervisor LLM needs to be invoked."""

from __future__ import annotations

import logging

from graph.models.state import MonitorMemory, State

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("monitor")

FORECAST_MISS_MW = 100.0
MAINTENANCE_LOOKAHEAD_TICKS = 12  # 3 hours
ROUTINE_INTERVAL_TICKS = 48  # 12 hours
ANCHOR_DRIFT_MW = 150.0  # cumulative drift from anchor before trigger
HEADROOM_BUFFER_MW = -100.0  # trigger only when demand exceeds supply by 100 MW
HEADROOM_LOOKAHEAD = 4  # intervals ahead to project headroom
COOLDOWN_TICKS = 12  # min ticks between supervisor calls
INTERVAL_HOURS = 0.25  # 15-min interval


def monitor(state: State) -> dict:
    tick: int = state.get("tick", 0)
    mem: MonitorMemory = state.get("monitor_memory", {})
    triggers: list[str] = []

    prev_forecast = mem.get("prev_renewables_forecast_mw")
    seen_alerts = set(mem.get("seen_alert_ids", []))
    seen_maints = set(mem.get("seen_maint_ids", []))
    last_sup_tick: int = mem.get("last_supervisor_tick", -ROUTINE_INTERVAL_TICKS)
    prev_storm: bool = mem.get("prev_active_storm", False)
    anchored_statuses = mem.get("anchored_asset_statuses")
    anchored_solar = mem.get("anchored_solar_mw")
    anchored_wind = mem.get("anchored_wind_mw")
    anchored_demand = mem.get("anchored_demand_mw")
    anchored_soc = mem.get("anchored_battery_soc_pct")

    log.debug(
        "tick=%d  last_sup_tick=%d  cooldown_remaining=%d",
        tick,
        last_sup_tick,
        max(0, COOLDOWN_TICKS - (tick - last_sup_tick)),
    )

    # ── first tick of the day ─────────────────────────────────────────────
    if tick == 0:
        triggers.append("first_tick")
        log.info("tick=%d  CHECK first_tick → TRIGGERED", tick)

    # ── forecast miss ─────────────────────────────────────────────────────
    if prev_forecast is not None:
        actual = state.get("renewables_mw", 0.0)
        miss = abs(actual - prev_forecast)
        if miss > FORECAST_MISS_MW:
            triggers.append(f"forecast_miss_{miss:.0f}MW")
            log.warning(
                "tick=%d  CHECK forecast_miss → TRIGGERED  actual=%.1f MW  forecast=%.1f MW  miss=%.1f MW (threshold=%.0f)",
                tick,
                actual,
                prev_forecast,
                miss,
                FORECAST_MISS_MW,
            )
        else:
            log.debug(
                "tick=%d  CHECK forecast_miss → ok  miss=%.1f MW < %.0f threshold",
                tick,
                miss,
                FORECAST_MISS_MW,
            )
    else:
        log.debug("tick=%d  CHECK forecast_miss → skipped (no previous forecast)", tick)

    # store current-tick forecast of next interval for comparison next tick
    solar_fc = state.get("solar_forecast")
    wind_fc = state.get("wind_forecast")
    new_prev_forecast: float | None = None
    if solar_fc and wind_fc and len(solar_fc.values) > 1 and len(wind_fc.values) > 1:
        new_prev_forecast = solar_fc.values[1] + wind_fc.values[1]

    # ── new storm alert ───────────────────────────────────────────────────
    for alert in state.get("storm_alerts", []):
        if alert.id not in seen_alerts:
            seen_alerts.add(alert.id)
            triggers.append(f"new_storm_alert_{alert.id}")
            log.warning(
                "tick=%d  CHECK storm_alert → TRIGGERED  new alert id=%s  winds=%.0f m/s",
                tick,
                alert.id,
                alert.wind_speed_ms,
            )
        else:
            log.debug("tick=%d  CHECK storm_alert → already seen id=%s", tick, alert.id)

    # ── storm state changed ───────────────────────────────────────────────
    active = state.get("active_storm", False)
    if active != prev_storm:
        label = "storm_started" if active else "storm_ended"
        triggers.append(label)
        log.warning("tick=%d  CHECK storm_state → TRIGGERED  %s", tick, label)
    else:
        log.debug("tick=%d  CHECK storm_state → unchanged  active=%s", tick, active)

    # ── maintenance approaching or just started (fire once per ID) ────────
    for mw in state.get("maintenance", []):
        from graph.simulator import _hhmm_to_tick

        start_tick = _hhmm_to_tick(mw.start)
        if mw.id in seen_maints:
            log.debug("tick=%d  CHECK maintenance → already seen id=%s", tick, mw.id)
            continue
        if mw.status == "pending":
            gap = start_tick - tick
            if 0 < gap <= MAINTENANCE_LOOKAHEAD_TICKS:
                seen_maints.add(mw.id)
                triggers.append(f"maintenance_approaching_{mw.id}")
                log.info(
                    "tick=%d  CHECK maintenance → TRIGGERED  approaching id=%s  asset=%s  starts_in=%d ticks",
                    tick,
                    mw.id,
                    mw.asset,
                    gap,
                )
            else:
                log.debug(
                    "tick=%d  CHECK maintenance → not yet  id=%s  gap=%d ticks",
                    tick,
                    mw.id,
                    gap,
                )
        elif mw.status == "active" and start_tick == tick:
            seen_maints.add(mw.id)
            triggers.append(f"maintenance_started_{mw.id}")
            log.info(
                "tick=%d  CHECK maintenance → TRIGGERED  started id=%s  asset=%s",
                tick,
                mw.id,
                mw.asset,
            )

    # ── asset status change (DB mode) ─────────────────────────────────────
    current_statuses = state.get("asset_statuses", [])
    current_status_map: dict[str, str] | None = None
    if current_statuses:
        current_status_map = {
            f"{s['asset_type']}:{s['asset_id']}": s["status"] for s in current_statuses
        }
        if anchored_statuses is not None:
            for key, new_status in current_status_map.items():
                old_status = anchored_statuses.get(key)
                if old_status is not None and old_status != new_status:
                    asset_type, asset_id = key.split(":", 1)
                    triggers.append(
                        f"asset_status_changed_{asset_type}_{asset_id}_{new_status}"
                    )
                    log.warning(
                        "tick=%d  CHECK asset_status → TRIGGERED  %s/%s  %s → %s",
                        tick,
                        asset_type,
                        asset_id,
                        old_status,
                        new_status,
                    )
        else:
            log.debug(
                "tick=%d  CHECK asset_status → first snapshot, anchoring %d assets",
                tick,
                len(current_status_map),
            )
    else:
        log.debug("tick=%d  CHECK asset_status → skipped (no statuses in state)", tick)

    # ── anchored drift (cumulative change since last supervisor call) ─────
    solar_mw = state.get("solar_mw", 0.0)
    wind_mw = state.get("wind_mw", 0.0)
    demand_mw = state.get("demand_mw", 0.0)
    battery_soc = state.get("battery_soc_pct", 0.0)

    if (
        anchored_solar is not None
        and anchored_wind is not None
        and anchored_demand is not None
        and anchored_soc is not None
    ):
        solar_drift = abs(solar_mw - anchored_solar)
        wind_drift = abs(wind_mw - anchored_wind)
        demand_drift = abs(demand_mw - anchored_demand)
        soc_drift = abs(battery_soc - anchored_soc)

        log.debug(
            "tick=%d  CHECK drift  solar=%.1f MW  wind=%.1f MW  demand=%.1f MW  soc=%.1f%%",
            tick,
            solar_drift,
            wind_drift,
            demand_drift,
            soc_drift,
        )

        if solar_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"solar_drift_{solar_drift:.0f}MW")
            log.info(
                "tick=%d  CHECK drift → TRIGGERED  solar_drift=%.1f MW > %.0f",
                tick,
                solar_drift,
                ANCHOR_DRIFT_MW,
            )
        if wind_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"wind_drift_{wind_drift:.0f}MW")
            log.info(
                "tick=%d  CHECK drift → TRIGGERED  wind_drift=%.1f MW > %.0f",
                tick,
                wind_drift,
                ANCHOR_DRIFT_MW,
            )
        if demand_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"demand_drift_{demand_drift:.0f}MW")
            log.info(
                "tick=%d  CHECK drift → TRIGGERED  demand_drift=%.1f MW > %.0f",
                tick,
                demand_drift,
                ANCHOR_DRIFT_MW,
            )
        if soc_drift > 25.0:
            triggers.append(f"soc_drift_{soc_drift:.0f}pct")
            log.info(
                "tick=%d  CHECK drift → TRIGGERED  soc_drift=%.1f%% > 25%%",
                tick,
                soc_drift,
            )
    else:
        log.debug("tick=%d  CHECK drift → skipped (no anchor yet)", tick)

    # ── aggregate headroom gap (MW-consistent) ────────────────────────────
    max_discharge = state.get("battery_max_discharge_mw", 0.0)
    line_limit = state.get("line_limit_mw", 0.0)
    reserve_pct = state.get("reserve_target_pct", state.get("reserve_floor_pct", 20.0))
    capacity_mwh = state.get("battery_capacity_mwh", 0.0)
    battery_energy = state.get("battery_energy_mwh", 0.0)

    reserve_energy_mwh = reserve_pct / 100.0 * capacity_mwh if capacity_mwh > 0 else 0.0
    energy_above_reserve = max(0.0, battery_energy - reserve_energy_mwh)
    available_discharge_mw = min(max_discharge, energy_above_reserve / INTERVAL_HOURS)

    headroom_now = (
        solar_mw + wind_mw + available_discharge_mw + line_limit
    ) - demand_mw
    log.debug(
        "tick=%d  CHECK headroom  supply=%.1f MW (solar=%.1f + wind=%.1f + batt=%.1f + grid=%.1f)  demand=%.1f MW  headroom=%.1f MW",
        tick,
        solar_mw + wind_mw + available_discharge_mw + line_limit,
        solar_mw,
        wind_mw,
        available_discharge_mw,
        line_limit,
        demand_mw,
        headroom_now,
    )
    if headroom_now < HEADROOM_BUFFER_MW:
        triggers.append(f"low_headroom_now_{headroom_now:.0f}MW")
        log.warning(
            "tick=%d  CHECK headroom → TRIGGERED  headroom=%.1f MW < %.0f threshold",
            tick,
            headroom_now,
            HEADROOM_BUFFER_MW,
        )

    solar_fc = state.get("solar_forecast")
    wind_fc = state.get("wind_forecast")
    demand_fc = state.get("demand_forecast")
    if solar_fc and wind_fc and demand_fc:
        for k in range(1, min(HEADROOM_LOOKAHEAD + 1, len(solar_fc.values))):
            future_supply = (
                solar_fc.values[k]
                + wind_fc.values[k]
                + available_discharge_mw
                + line_limit
            )
            future_demand = demand_fc.values[k]
            future_headroom = future_supply - future_demand
            if future_headroom < HEADROOM_BUFFER_MW:
                triggers.append(f"low_headroom_t+{k}_{future_headroom:.0f}MW")
                log.warning(
                    "tick=%d  CHECK headroom_forecast → TRIGGERED  t+%d  headroom=%.1f MW",
                    tick,
                    k,
                    future_headroom,
                )
                break

    # ── routine review ────────────────────────────────────────────────────
    ticks_since = tick - last_sup_tick
    if ticks_since >= ROUTINE_INTERVAL_TICKS and not triggers:
        triggers.append("routine_review")
        log.info(
            "tick=%d  CHECK routine → TRIGGERED  %d ticks since last supervisor call",
            tick,
            ticks_since,
        )

    critical = any(
        t.startswith(("first_tick", "storm_started", "storm_ended", "new_storm_alert"))
        for t in triggers
    )
    in_cooldown = (tick - last_sup_tick) < COOLDOWN_TICKS
    should_call = len(triggers) > 0 and (critical or not in_cooldown)

    if triggers:
        if should_call:
            log.info(
                "tick=%d  DECISION → CALL supervisor  triggers=%s  critical=%s",
                tick,
                triggers,
                critical,
            )
        else:
            log.info(
                "tick=%d  DECISION → SUPPRESS (cooldown)  triggers=%s  cooldown_remaining=%d",
                tick,
                triggers,
                COOLDOWN_TICKS - (tick - last_sup_tick),
            )
    else:
        log.debug("tick=%d  DECISION → SKIP (no triggers)", tick)

    # ── build updated memory ──────────────────────────────────────────────
    new_mem: MonitorMemory = {
        "prev_renewables_forecast_mw": new_prev_forecast,
        "seen_alert_ids": sorted(seen_alerts),
        "seen_maint_ids": sorted(seen_maints),
        "last_supervisor_tick": tick if should_call else last_sup_tick,
        "prev_active_storm": active,
        "anchored_asset_statuses": (
            current_status_map
            if should_call and current_status_map is not None
            else anchored_statuses
        ),
        "anchored_solar_mw": solar_mw if should_call else anchored_solar,
        "anchored_wind_mw": wind_mw if should_call else anchored_wind,
        "anchored_demand_mw": demand_mw if should_call else anchored_demand,
        "anchored_battery_soc_pct": battery_soc if should_call else anchored_soc,
    }

    if should_call:
        log.debug("tick=%d  anchors updated to current values", tick)

    return {
        "should_call_supervisor": should_call,
        "monitor_triggers": triggers,
        "monitor_memory": new_mem,
    }
