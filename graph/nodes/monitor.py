"""LangGraph node: decides whether the Supervisor LLM needs to be invoked."""

from __future__ import annotations

from graph.models.state import State

FORECAST_MISS_MW = 30.0
MAINTENANCE_LOOKAHEAD_TICKS = 12  # 3 hours
ROUTINE_INTERVAL_TICKS = 12      # 3 hours


class _MonitorMemory:
    """Persists across ticks so the monitor can detect changes."""
    prev_renewables_forecast_mw: float | None = None
    seen_alert_ids: set[str] = set()
    last_supervisor_tick: int = -ROUTINE_INTERVAL_TICKS
    prev_active_storm: bool = False


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

    # ── maintenance approaching ───────────────────────────────────────────
    for mw in state.get("maintenance", []):
        if mw.status == "pending":
            from graph.simulator import _hhmm_to_tick
            start_tick = _hhmm_to_tick(mw.start)
            if 0 < (start_tick - tick) <= MAINTENANCE_LOOKAHEAD_TICKS:
                triggers.append(f"maintenance_approaching_{mw.id}")

    # ── routine review ────────────────────────────────────────────────────
    if tick - _mem.last_supervisor_tick >= ROUTINE_INTERVAL_TICKS and not triggers:
        triggers.append("routine_review")

    should_call = len(triggers) > 0
    if should_call:
        _mem.last_supervisor_tick = tick

    return {
        "should_call_supervisor": should_call,
        "monitor_triggers": triggers,
    }
