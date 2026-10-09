"""LangGraph node: decides whether the Supervisor LLM needs to be invoked."""

from __future__ import annotations

from graph.models.state import State

FORECAST_MISS_MW = 30.0
MAINTENANCE_LOOKAHEAD_TICKS = 12  # 3 hours
ROUTINE_INTERVAL_TICKS = 12      # 3 hours
ANCHOR_DRIFT_MW = 25.0            # cumulative drift from anchor before trigger
HEADROOM_BUFFER_MW = 20.0         # min supply-demand headroom before trigger
HEADROOM_LOOKAHEAD = 4            # intervals ahead to project headroom


class _MonitorMemory:
    """Persists across ticks so the monitor can detect changes."""
    prev_renewables_forecast_mw: float | None = None
    seen_alert_ids: set[str] = set()
    last_supervisor_tick: int = -ROUTINE_INTERVAL_TICKS
    prev_active_storm: bool = False
    anchored_asset_statuses: dict[tuple[str, str], str] | None = None
    anchored_solar_mw: float | None = None
    anchored_wind_mw: float | None = None
    anchored_demand_mw: float | None = None
    anchored_battery_soc_pct: float | None = None


_mem = _MonitorMemory()


def reset_monitor() -> None:
    """Reset between simulation runs."""
    global _mem
    _mem = _MonitorMemory()


def monitor(state: State) -> dict:
    tick: int = state.get("tick", 0)
    triggers: list[str] = []

    # ── first tick of the day ─────────────────────────────────────────────
    if tick == 0:
        triggers.append("first_tick")

    # ── forecast miss ─────────────────────────────────────────────────────
    if _mem.prev_renewables_forecast_mw is not None:
        actual = state.get("renewables_mw", 0.0)
        miss = abs(actual - _mem.prev_renewables_forecast_mw)
        if miss > FORECAST_MISS_MW:
            triggers.append(f"forecast_miss_{miss:.0f}MW")

    # store current-tick forecast of next interval for comparison next tick
    solar_fc = state.get("solar_forecast")
    wind_fc = state.get("wind_forecast")
    if solar_fc and wind_fc and len(solar_fc.values) > 1 and len(wind_fc.values) > 1:
        _mem.prev_renewables_forecast_mw = solar_fc.values[1] + wind_fc.values[1]
    else:
        _mem.prev_renewables_forecast_mw = None

    # ── new storm alert ───────────────────────────────────────────────────
    for alert in state.get("storm_alerts", []):
        if alert.id not in _mem.seen_alert_ids:
            _mem.seen_alert_ids.add(alert.id)
            triggers.append(f"new_storm_alert_{alert.id}")

    # ── storm state changed ───────────────────────────────────────────────
    active = state.get("active_storm", False)
    if active != _mem.prev_active_storm:
        triggers.append("storm_started" if active else "storm_ended")
    _mem.prev_active_storm = active

    # ── maintenance approaching or just started ─────────────────────────
    for mw in state.get("maintenance", []):
        from graph.simulator import _hhmm_to_tick
        start_tick = _hhmm_to_tick(mw.start)
        if mw.status == "pending":
            if 0 < (start_tick - tick) <= MAINTENANCE_LOOKAHEAD_TICKS:
                triggers.append(f"maintenance_approaching_{mw.id}")
        elif mw.status == "active" and start_tick == tick:
            triggers.append(f"maintenance_started_{mw.id}")

    # ── asset status change (DB mode) ──────────────────────────────────────
    current_statuses = state.get("asset_statuses", [])
    current_status_map: dict[tuple[str, str], str] | None = None
    if current_statuses:
        current_status_map = {
            (s["asset_type"], s["asset_id"]): s["status"]
            for s in current_statuses
        }
        if _mem.anchored_asset_statuses is not None:
            for key, new_status in current_status_map.items():
                old_status = _mem.anchored_asset_statuses.get(key)
                if old_status is not None and old_status != new_status:
                    triggers.append(
                        f"asset_status_changed_{key[0]}_{key[1]}_{new_status}"
                    )

    # ── anchored drift (cumulative change since last supervisor call) ────
    solar_mw = state.get("solar_mw", 0.0)
    wind_mw = state.get("wind_mw", 0.0)
    demand_mw = state.get("demand_mw", 0.0)
    battery_soc = state.get("battery_soc_pct", 0.0)

    if _mem.anchored_solar_mw is not None:
        solar_drift = abs(solar_mw - _mem.anchored_solar_mw)
        wind_drift = abs(wind_mw - _mem.anchored_wind_mw)
        demand_drift = abs(demand_mw - _mem.anchored_demand_mw)
        soc_drift = abs(battery_soc - _mem.anchored_battery_soc_pct)

        if solar_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"solar_drift_{solar_drift:.0f}MW")
        if wind_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"wind_drift_{wind_drift:.0f}MW")
        if demand_drift > ANCHOR_DRIFT_MW:
            triggers.append(f"demand_drift_{demand_drift:.0f}MW")
        if soc_drift > 10.0:
            triggers.append(f"soc_drift_{soc_drift:.0f}pct")

    # ── aggregate headroom gap ────────────────────────────────────────────
    max_discharge = state.get("battery_max_discharge_mw", 0.0)
    line_limit = state.get("line_limit_mw", 150.0)
    reserve_pct = state.get("reserve_target_pct", state.get("reserve_floor_pct", 20.0))
    capacity = state.get("battery_capacity_mwh", 400.0)
    reserve_mw = reserve_pct / 100.0 * capacity

    headroom_now = (solar_mw + wind_mw + max_discharge + line_limit) - (
        demand_mw + reserve_mw
    )
    if headroom_now < HEADROOM_BUFFER_MW:
        triggers.append(f"low_headroom_now_{headroom_now:.0f}MW")

    solar_fc = state.get("solar_forecast")
    wind_fc = state.get("wind_forecast")
    demand_fc = state.get("demand_forecast")
    if solar_fc and wind_fc and demand_fc:
        for k in range(1, min(HEADROOM_LOOKAHEAD + 1, len(solar_fc.values))):
            future_supply = solar_fc.values[k] + wind_fc.values[k] + max_discharge + line_limit
            future_demand = demand_fc.values[k] + reserve_mw
            if future_supply - future_demand < HEADROOM_BUFFER_MW:
                triggers.append(f"low_headroom_t+{k}_{future_supply - future_demand:.0f}MW")
                break

    # ── routine review ────────────────────────────────────────────────────
    if tick - _mem.last_supervisor_tick >= ROUTINE_INTERVAL_TICKS and not triggers:
        triggers.append("routine_review")

    should_call = len(triggers) > 0
    if should_call:
        _mem.last_supervisor_tick = tick
        if current_status_map is not None:
            _mem.anchored_asset_statuses = current_status_map
        _mem.anchored_solar_mw = solar_mw
        _mem.anchored_wind_mw = wind_mw
        _mem.anchored_demand_mw = demand_mw
        _mem.anchored_battery_soc_pct = battery_soc

    return {
        "should_call_supervisor": should_call,
        "monitor_triggers": triggers,
    }
