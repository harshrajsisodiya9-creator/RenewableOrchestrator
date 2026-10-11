"""LangGraph node: decides whether the Supervisor or Planner needs to be invoked."""

from __future__ import annotations

import logging

from graph.models.state import MonitorMemory, PlannerMemory, State

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("monitor")

FORECAST_MISS_MW = 100.0
MAINTENANCE_LOOKAHEAD_TICKS = 12  # 3 hours
ROUTINE_INTERVAL_TICKS = 48  # 12 hours
ANCHOR_DRIFT_MW = 150.0
HEADROOM_BUFFER_MW = -100.0
HEADROOM_LOOKAHEAD = 4
COOLDOWN_TICKS = 12
INTERVAL_HOURS = 0.25

# planner-specific thresholds
PLANNER_COOLDOWN_TICKS = 4  # 1 hour min between planner calls
DEVIATION_THRESHOLD_PCT = 0.20  # 20% renewables deviation
DEVIATION_CONSECUTIVE = 4  # ticks of sustained deviation
DEMAND_CHANGE_PCT = 0.30  # 30% demand change for supervisor trigger
SOC_FLOOR_PROXIMITY_PCT = 2.0  # within 2 pp of floor


def monitor(state: State) -> dict:
    tick: int = state.get("tick", 0)
    mem: MonitorMemory = state.get("monitor_memory", {})
    pmem: PlannerMemory = state.get("planner_memory", {})
    triggers: list[str] = []
    planner_triggers: list[str] = []

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
    prev_demand = mem.get("prev_demand_mw")
    prev_solar_above_1 = mem.get("prev_solar_above_1", False)

    last_planner_tick: int = pmem.get("last_planner_tick", -PLANNER_COOLDOWN_TICKS * 10)
    consec_deviation: int = pmem.get("consecutive_deviation_ticks", 0)

    log.debug(
        "tick=%d  last_sup_tick=%d  cooldown_remaining=%d",
        tick, last_sup_tick, max(0, COOLDOWN_TICKS - (tick - last_sup_tick)),
    )

    # ══════════════════════════════════════════════════════════════════════
    # PLANNER TRIGGERS
    # ══════════════════════════════════════════════════════════════════════

    # ── first tick of the day ─────────────────────────────────────────────
    if tick == 0:
        planner_triggers.append("first_tick")
        triggers.append("first_tick")
        log.info("tick=%d  CHECK first_tick → TRIGGERED (planner + supervisor)", tick)

    # ── new storm alert → always triggers planner (bypasses cooldown) ─────
    new_storm_alert = False
    for alert in state.get("storm_alerts", []):
        if alert.id not in seen_alerts:
            seen_alerts.add(alert.id)
            planner_triggers.append(f"new_storm_alert_{alert.id}")
            triggers.append(f"new_storm_alert_{alert.id}")
            new_storm_alert = True
            log.warning(
                "tick=%d  CHECK storm_alert → TRIGGERED  new alert id=%s  winds=%.0f m/s",
                tick, alert.id, alert.wind_speed_ms,
            )
        else:
            log.debug("tick=%d  CHECK storm_alert → already seen id=%s", tick, alert.id)

    # ── renewables deviation > 20% for 4+ consecutive ticks ──────────────
    solar_fc_obj = state.get("solar_forecast")
    wind_fc_obj = state.get("wind_forecast")
    actual_ren = state.get("renewables_mw", 0.0)
    if solar_fc_obj and wind_fc_obj and len(solar_fc_obj.values) > 0 and len(wind_fc_obj.values) > 0:
        forecast_ren = solar_fc_obj.values[0] + wind_fc_obj.values[0]
        if forecast_ren > 0 and abs(actual_ren - forecast_ren) / forecast_ren > DEVIATION_THRESHOLD_PCT:
            consec_deviation += 1
        else:
            consec_deviation = 0

        if consec_deviation >= DEVIATION_CONSECUTIVE:
            planner_triggers.append(f"renewables_deviation_{consec_deviation}_ticks")
            log.info("tick=%d  CHECK renewables_deviation → TRIGGERED  %d consecutive ticks", tick, consec_deviation)
            consec_deviation = 0

    # ── supervisor requests replan ────────────────────────────────────────
    if state.get("request_replan", False):
        planner_triggers.append("supervisor_request_replan")
        log.info("tick=%d  CHECK request_replan → TRIGGERED", tick)

    # ══════════════════════════════════════════════════════════════════════
    # SUPERVISOR TRIGGERS
    # ══════════════════════════════════════════════════════════════════════

    # ── forecast miss ─────────────────────────────────────────────────────
    if prev_forecast is not None:
        miss = abs(actual_ren - prev_forecast)
        if miss > FORECAST_MISS_MW:
            triggers.append(f"forecast_miss_{miss:.0f}MW")
            log.warning(
                "tick=%d  CHECK forecast_miss → TRIGGERED  actual=%.1f MW  forecast=%.1f MW  miss=%.1f MW",
                tick, actual_ren, prev_forecast, miss,
            )
        else:
            log.debug("tick=%d  CHECK forecast_miss → ok  miss=%.1f MW < %.0f", tick, miss, FORECAST_MISS_MW)
    else:
        log.debug("tick=%d  CHECK forecast_miss → skipped (no previous forecast)", tick)

    # store current-tick forecast of next interval for comparison next tick
    new_prev_forecast: float | None = None
    if solar_fc_obj and wind_fc_obj and len(solar_fc_obj.values) > 1 and len(wind_fc_obj.values) > 1:
        new_prev_forecast = solar_fc_obj.values[1] + wind_fc_obj.values[1]

    # ── storm state changed ───────────────────────────────────────────────
    active = state.get("active_storm", False)
    if active != prev_storm:
        label = "storm_started" if active else "storm_ended"
        triggers.append(label)
        log.warning("tick=%d  CHECK storm_state → TRIGGERED  %s", tick, label)
    else:
        log.debug("tick=%d  CHECK storm_state → unchanged  active=%s", tick, active)

    # ── sunrise: solar > 1 MW transition ─────────────────────────────────
    solar_mw = state.get("solar_mw", 0.0)
    solar_above_1 = solar_mw > 1.0
    if solar_above_1 and not prev_solar_above_1:
        triggers.append("sunrise")
        log.info("tick=%d  CHECK sunrise → TRIGGERED  solar=%.1f MW", tick, solar_mw)
    elif not solar_above_1 and prev_solar_above_1:
        triggers.append("sunset")
        log.info("tick=%d  CHECK sunset → TRIGGERED  solar=%.1f MW", tick, solar_mw)

    # ── demand change > 30% vs previous tick ─────────────────────────────
    demand_mw = state.get("demand_mw", 0.0)
    if prev_demand is not None and prev_demand > 0:
        demand_change = abs(demand_mw - prev_demand) / prev_demand
        if demand_change > DEMAND_CHANGE_PCT:
            triggers.append(f"demand_change_{demand_change:.0%}")
            log.info("tick=%d  CHECK demand_change → TRIGGERED  %.0f%%", tick, demand_change * 100)

    # ── SoC within 2 pp of current floor ─────────────────────────────────
    battery_soc = state.get("battery_soc_pct", 0.0)
    day_plan = state.get("day_plan")
    if day_plan is not None:
        h = tick // 4
        m = (tick % 4) * 15
        t_str = f"{h:02d}:{m:02d}"
        current_floor = 35.0
        for w in day_plan.floor_schedule:
            if w.start <= t_str < w.end:
                current_floor = w.floor_pct
                break
        if abs(battery_soc - current_floor) <= SOC_FLOOR_PROXIMITY_PCT:
            triggers.append(f"soc_near_floor_{battery_soc:.1f}_vs_{current_floor:.0f}")
            log.info("tick=%d  CHECK soc_near_floor → TRIGGERED  soc=%.1f  floor=%.0f", tick, battery_soc, current_floor)

    # ── entering/leaving peak window ─────────────────────────────────────
    features = state.get("features", {})
    peak_ticks_list = features.get("peak_ticks", [])
    if peak_ticks_list:
        in_peak = tick in peak_ticks_list
        prev_in_peak = (tick - 1) in peak_ticks_list if tick > 0 else False
        if in_peak and not prev_in_peak:
            triggers.append("entering_peak")
            log.info("tick=%d  CHECK peak_window → TRIGGERED  entering peak", tick)
        elif not in_peak and prev_in_peak:
            triggers.append("leaving_peak")
            log.info("tick=%d  CHECK peak_window → TRIGGERED  leaving peak", tick)

    # ── maintenance approaching or just started ──────────────────────────
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
                log.info("tick=%d  CHECK maintenance → TRIGGERED  approaching id=%s  starts_in=%d ticks", tick, mw.id, gap)
        elif mw.status == "active" and start_tick == tick:
            seen_maints.add(mw.id)
            triggers.append(f"maintenance_started_{mw.id}")
            log.info("tick=%d  CHECK maintenance → TRIGGERED  started id=%s", tick, mw.id)

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
                    triggers.append(f"asset_status_changed_{asset_type}_{asset_id}_{new_status}")
                    log.warning("tick=%d  CHECK asset_status → TRIGGERED  %s/%s  %s → %s", tick, asset_type, asset_id, old_status, new_status)

    # ── anchored drift ───────────────────────────────────────────────────
    wind_mw = state.get("wind_mw", 0.0)

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

        if solar_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"solar_drift_{solar_drift:.0f}MW")
        if wind_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"wind_drift_{wind_drift:.0f}MW")
        if demand_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"demand_drift_{demand_drift:.0f}MW")
        if soc_drift > 25.0:
            triggers.append(f"soc_drift_{soc_drift:.0f}pct")

    # ── aggregate headroom gap ───────────────────────────────────────────
    max_discharge = state.get("battery_max_discharge_mw", 0.0)
    line_limit = state.get("line_limit_mw", 0.0)
    reserve_pct = state.get("reserve_target_pct", state.get("reserve_floor_pct", 20.0))
    capacity_mwh = state.get("battery_capacity_mwh", 0.0)
    battery_energy = state.get("battery_energy_mwh", 0.0)

    reserve_energy_mwh = reserve_pct / 100.0 * capacity_mwh if capacity_mwh > 0 else 0.0
    energy_above_reserve = max(0.0, battery_energy - reserve_energy_mwh)
    available_discharge_mw = min(max_discharge, energy_above_reserve / INTERVAL_HOURS)

    headroom_now = (solar_mw + wind_mw + available_discharge_mw + line_limit) - demand_mw
    if headroom_now < HEADROOM_BUFFER_MW:
        triggers.append(f"low_headroom_now_{headroom_now:.0f}MW")
        log.warning("tick=%d  CHECK headroom → TRIGGERED  headroom=%.1f MW", tick, headroom_now)

    demand_fc = state.get("demand_forecast")
    if solar_fc_obj and wind_fc_obj and demand_fc:
        for k in range(1, min(HEADROOM_LOOKAHEAD + 1, len(solar_fc_obj.values))):
            future_supply = solar_fc_obj.values[k] + wind_fc_obj.values[k] + available_discharge_mw + line_limit
            future_demand = demand_fc.values[k]
            future_headroom = future_supply - future_demand
            if future_headroom < HEADROOM_BUFFER_MW:
                triggers.append(f"low_headroom_t+{k}_{future_headroom:.0f}MW")
                break

    # ── routine review ───────────────────────────────────────────────────
    ticks_since = tick - last_sup_tick
    if ticks_since >= ROUTINE_INTERVAL_TICKS and not triggers:
        triggers.append("routine_review")
        log.info("tick=%d  CHECK routine → TRIGGERED  %d ticks since last supervisor call", tick, ticks_since)

    # ══════════════════════════════════════════════════════════════════════
    # DECISIONS
    # ══════════════════════════════════════════════════════════════════════

    # Supervisor decision
    critical = any(
        t.startswith(("first_tick", "storm_started", "storm_ended", "new_storm_alert"))
        for t in triggers
    )
    in_cooldown = (tick - last_sup_tick) < COOLDOWN_TICKS
    should_call_supervisor = len(triggers) > 0 and (critical or not in_cooldown)

    # Planner decision
    planner_in_cooldown = (tick - last_planner_tick) < PLANNER_COOLDOWN_TICKS
    should_call_planner = len(planner_triggers) > 0 and (new_storm_alert or not planner_in_cooldown)

    if should_call_planner:
        should_call_supervisor = True
        log.info("tick=%d  DECISION → CALL planner  triggers=%s", tick, planner_triggers)

    if triggers:
        if should_call_supervisor:
            log.info("tick=%d  DECISION → CALL supervisor  triggers=%s  critical=%s", tick, triggers, critical)
        else:
            log.info("tick=%d  DECISION → SUPPRESS (cooldown)  triggers=%s", tick, triggers)
    else:
        log.debug("tick=%d  DECISION → SKIP (no triggers)", tick)

    # ── build updated memory ─────────────────────────────────────────────
    new_mem: MonitorMemory = {
        "prev_renewables_forecast_mw": new_prev_forecast,
        "seen_alert_ids": sorted(seen_alerts),
        "seen_maint_ids": sorted(seen_maints),
        "last_supervisor_tick": tick if should_call_supervisor else last_sup_tick,
        "prev_active_storm": active,
        "anchored_asset_statuses": (
            current_status_map
            if should_call_supervisor and current_status_map is not None
            else anchored_statuses
        ),
        "anchored_solar_mw": solar_mw if should_call_supervisor else anchored_solar,
        "anchored_wind_mw": wind_mw if should_call_supervisor else anchored_wind,
        "anchored_demand_mw": demand_mw if should_call_supervisor else anchored_demand,
        "anchored_battery_soc_pct": battery_soc if should_call_supervisor else anchored_soc,
        "prev_demand_mw": demand_mw,
        "prev_solar_above_1": solar_above_1,
    }

    new_pmem: PlannerMemory = {
        "last_planner_tick": tick if should_call_planner else last_planner_tick,
        "consecutive_deviation_ticks": consec_deviation,
    }

    return {
        "should_call_supervisor": should_call_supervisor,
        "should_call_planner": should_call_planner,
        "monitor_triggers": triggers,
        "monitor_memory": new_mem,
        "planner_memory": new_pmem,
    }
