"""LangGraph node: reads the simulator for the current tick and populates State."""

from __future__ import annotations

import logging
import os

from graph.models.state import Forecast, State
from graph.simulator import Simulator

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("data_collector")

_simulator: Simulator | None = None

_db_project_id: int | None = None
_db_solar_farms: list[dict] = []
_db_wind_farms: list[dict] = []
_wind_physics: dict = {}


def init_simulator(sim: Simulator) -> None:
    """Call once at startup to inject the shared Simulator instance."""
    global _simulator
    _simulator = sim


def init_data_collector_db(
    project_id: int,
    solar_farms: list[dict],
    wind_farms: list[dict],
    wind_physics: dict | None = None,
) -> None:
    """Call once at startup in DB mode to provide farm configs for masking."""
    global _db_project_id, _db_solar_farms, _db_wind_farms, _wind_physics
    _db_project_id = project_id
    _db_solar_farms = solar_farms
    _db_wind_farms = wind_farms
    if wind_physics:
        _wind_physics = wind_physics


def _apply_asset_statuses(obs: dict, statuses: list[dict]) -> dict:
    """Zero out tripped assets in the observation dict."""
    total_solar_cap = sum(f["capacity_mw"] for f in _db_solar_farms)
    total_wind_cap = sum(f["capacity_mw"] for f in _db_wind_farms)

    tripped_solar_cap = sum(
        next((f["capacity_mw"] for f in _db_solar_farms if f["id"] == s["asset_id"]), 0)
        for s in statuses
        if s["asset_type"] == "solar" and s["status"] == "tripped"
    )
    tripped_wind_cap = sum(
        next((f["capacity_mw"] for f in _db_wind_farms if f["id"] == s["asset_id"]), 0)
        for s in statuses
        if s["asset_type"] == "wind" and s["status"] == "tripped"
    )

    if tripped_solar_cap > 0 and total_solar_cap > 0:
        factor = 1 - tripped_solar_cap / total_solar_cap
        obs["solar_mw"] = round(obs["solar_mw"] * factor, 2)
        obs["solar_forecast"] = Forecast(
            values=[round(v * factor, 2) for v in obs["solar_forecast"].values]
        )

    if tripped_wind_cap > 0 and total_wind_cap > 0:
        factor = 1 - tripped_wind_cap / total_wind_cap
        obs["wind_mw"] = round(obs["wind_mw"] * factor, 2)
        obs["wind_forecast"] = Forecast(
            values=[round(v * factor, 2) for v in obs["wind_forecast"].values]
        )

    obs["renewables_mw"] = round(obs["solar_mw"] + obs["wind_mw"], 2)

    tripped_batteries = [
        s["asset_id"]
        for s in statuses
        if s["asset_type"] == "battery" and s["status"] == "tripped"
    ]
    total_batteries = [s["asset_id"] for s in statuses if s["asset_type"] == "battery"]

    if tripped_batteries and total_batteries:
        online_ratio = 1 - len(tripped_batteries) / len(total_batteries)
        obs["battery_max_charge_mw"] = round(
            obs.get("battery_max_charge_mw", 0) * online_ratio, 2
        )
        obs["battery_max_discharge_mw"] = round(
            obs.get("battery_max_discharge_mw", 0) * online_ratio, 2
        )
        obs["battery_capacity_mwh"] = round(
            obs.get("battery_capacity_mwh", 0) * online_ratio, 2
        )
        obs["battery_energy_mwh"] = round(
            obs.get("battery_energy_mwh", 0) * online_ratio, 2
        )
        obs["battery_min_energy_mwh"] = round(
            obs.get("battery_min_energy_mwh", 0) * online_ratio, 2
        )
        obs["battery_max_energy_mwh"] = round(
            obs.get("battery_max_energy_mwh", 0) * online_ratio, 2
        )

    grid_tripped = any(
        s["asset_type"] == "grid" and s["status"] == "tripped" for s in statuses
    )
    if grid_tripped:
        obs["line_limit_mw"] = 0.0

    return obs


def _overlay_event_on_forecasts(
    obs: dict,
    tick: int,
    start_tick: int,
    end_tick: int,
    ev_type: str,
    wind_speed_ms: float | None,
    line_derate_mw: float | None,
    pct_drop: float | None,
    extra_mw: float | None,
    multiplier: float | None,
    targets: list[str],
) -> None:
    """Adjust forecast values for positions that overlap the event window."""
    from graph.simulator import FORECAST_HORIZON, _wind_power_factor

    solar_fc: Forecast | None = obs.get("solar_forecast")
    wind_fc: Forecast | None = obs.get("wind_forecast")
    demand_fc: Forecast | None = obs.get("demand_forecast")
    price_fc: Forecast | None = obs.get("price_forecast")

    total_wind = sum(f["capacity_mw"] for f in _db_wind_farms) if _db_wind_farms else 0
    total_solar = sum(f["capacity_mw"] for f in _db_solar_farms) if _db_solar_farms else 0

    horizon = FORECAST_HORIZON
    if solar_fc:
        horizon = min(horizon, len(solar_fc.values))

    for k in range(horizon):
        ft = tick + k
        if not (start_tick <= ft < end_tick):
            continue

        if ev_type == "storm":
            if wind_speed_ms is not None and wind_fc and total_wind > 0:
                pf = _wind_power_factor(
                    wind_speed_ms,
                    _wind_physics.get("cut_in_ms", 3.0),
                    _wind_physics.get("rated_ms", 12.0),
                    _wind_physics.get("cut_out_ms", 25.0),
                )
                wind_fc.values[k] = round(total_wind * pf, 2)

        elif ev_type == "cloud":
            if pct_drop is not None and solar_fc:
                solar_fc.values[k] = round(solar_fc.values[k] * (1 - pct_drop / 100), 2)

        elif ev_type == "wind_lull":
            if pct_drop is not None and wind_fc:
                wind_fc.values[k] = round(wind_fc.values[k] * (1 - pct_drop / 100), 2)

        elif ev_type == "demand_spike":
            if extra_mw is not None and demand_fc:
                demand_fc.values[k] = round(demand_fc.values[k] + extra_mw, 2)

        elif ev_type == "price_spike":
            if multiplier is not None and price_fc:
                price_fc.values[k] = round(price_fc.values[k] * multiplier, 4)

        elif ev_type == "maintenance":
            for target in targets:
                if any(f["id"] == target for f in _db_wind_farms) and total_wind > 0 and wind_fc:
                    cap = next(f["capacity_mw"] for f in _db_wind_farms if f["id"] == target)
                    wind_fc.values[k] = round(wind_fc.values[k] * (1 - cap / total_wind), 2)
                elif any(f["id"] == target for f in _db_solar_farms) and total_solar > 0 and solar_fc:
                    cap = next(f["capacity_mw"] for f in _db_solar_farms if f["id"] == target)
                    solar_fc.values[k] = round(solar_fc.values[k] * (1 - cap / total_solar), 2)


def _apply_db_events(obs: dict, tick: int, project_id: int) -> dict:
    """Query DB events and overlay their effects on the simulator observation."""
    from api.database import SessionLocal
    from api.models import Event
    from graph.simulator import _hhmm_to_tick, _wind_power_factor

    db = SessionLocal()
    try:
        events = db.query(Event).filter(Event.project_id == project_id).all()
    finally:
        db.close()

    if not events:
        return obs

    from graph.models.state import MaintenanceWindow, StormAlert

    storm_alerts: list[StormAlert] = list(obs.get("storm_alerts", []))
    maint_windows: list[MaintenanceWindow] = list(obs.get("maintenance", []))
    has_active_storm = obs.get("active_storm", False)

    total_wind = sum(f["capacity_mw"] for f in _db_wind_farms) if _db_wind_farms else 0
    total_solar = sum(f["capacity_mw"] for f in _db_solar_farms) if _db_solar_farms else 0

    for ev in events:
        st = _hhmm_to_tick(ev.start_time)
        et = _hhmm_to_tick(ev.end_time)
        at = _hhmm_to_tick(ev.alert_time) if ev.alert_time else None

        active = st <= tick < et
        alerted_pre = (
            ev.visibility == "alerted"
            and at is not None
            and at <= tick < st
        )

        # ── active event: modify actuals ──
        if active:
            if ev.type == "storm":
                has_active_storm = True
                if ev.wind_speed_ms is not None and total_wind > 0:
                    obs["wind_speed_ms"] = ev.wind_speed_ms
                    pf = _wind_power_factor(
                        ev.wind_speed_ms,
                        _wind_physics.get("cut_in_ms", 3.0),
                        _wind_physics.get("rated_ms", 12.0),
                        _wind_physics.get("cut_out_ms", 25.0),
                    )
                    obs["wind_mw"] = round(total_wind * pf, 2)
                if ev.line_derate_mw is not None:
                    obs["line_limit_mw"] = min(
                        obs.get("line_limit_mw", 0), ev.line_derate_mw
                    )

            elif ev.type == "cloud" and ev.pct_drop is not None:
                obs["solar_mw"] = round(obs["solar_mw"] * (1 - ev.pct_drop / 100), 2)

            elif ev.type == "wind_lull" and ev.pct_drop is not None:
                obs["wind_mw"] = round(obs["wind_mw"] * (1 - ev.pct_drop / 100), 2)

            elif ev.type == "demand_spike" and ev.extra_mw is not None:
                obs["demand_mw"] = round(obs["demand_mw"] + ev.extra_mw, 2)

            elif ev.type == "price_spike" and ev.multiplier is not None:
                obs["price_per_kwh"] = round(obs["price_per_kwh"] * ev.multiplier, 4)

            elif ev.type == "maintenance" and ev.targets:
                for target in ev.targets:
                    if any(f["id"] == target for f in _db_wind_farms) and total_wind > 0:
                        cap = next(f["capacity_mw"] for f in _db_wind_farms if f["id"] == target)
                        obs["wind_mw"] = round(obs["wind_mw"] * (1 - cap / total_wind), 2)
                    elif any(f["id"] == target for f in _db_solar_farms) and total_solar > 0:
                        cap = next(f["capacity_mw"] for f in _db_solar_farms if f["id"] == target)
                        obs["solar_mw"] = round(obs["solar_mw"] * (1 - cap / total_solar), 2)

        # ── forecasts: only for alerted events ──
        if ev.visibility == "alerted" and (alerted_pre or active):
            _overlay_event_on_forecasts(
                obs, tick, st, et,
                ev.type, ev.wind_speed_ms, ev.line_derate_mw,
                ev.pct_drop, ev.extra_mw, ev.multiplier,
                ev.targets or [],
            )

        # ── storm alerts (alerted: from alert_time; surprise: once active) ──
        if ev.type == "storm" and (alerted_pre or active):
            storm_alerts.append(StormAlert(
                id=f"db_{ev.id}",
                alert_time=ev.alert_time or ev.start_time,
                storm_start=ev.start_time,
                storm_end=ev.end_time,
                wind_speed_ms=ev.wind_speed_ms or 0,
                line_limit_mw=ev.line_derate_mw or obs.get("line_limit_mw", 0),
                notice=f"Event {ev.id}",
            ))

        # ── maintenance windows ──
        if ev.type == "maintenance":
            if tick < st:
                status = "pending"
            elif active:
                status = "active"
            else:
                status = "completed"
            if ev.visibility == "alerted" or active or tick >= et:
                maint_windows.append(MaintenanceWindow(
                    id=f"db_{ev.id}",
                    asset=ev.targets[0] if ev.targets else "unknown",
                    kind="scheduled",
                    start=ev.start_time,
                    end=ev.end_time,
                    status=status,
                ))

    obs["renewables_mw"] = round(obs.get("solar_mw", 0) + obs.get("wind_mw", 0), 2)
    obs["storm_alerts"] = storm_alerts
    obs["active_storm"] = has_active_storm
    obs["maintenance"] = maint_windows

    return obs


def data_collector(state: State) -> dict:
    """Observe the world at the current tick and return State updates."""
    if _simulator is None:
        raise RuntimeError(
            "Simulator not initialised — call init_simulator() before "
            "running the graph."
        )

    tick = state.get("tick", 0)
    obs = _simulator.observe(tick)

    log.info(
        "tick=%d  solar=%.1f MW  wind=%.1f MW  demand=%.1f MW  "
        "battery_soc=%.1f%%  price=%.2f ₹/kWh  line_limit=%.0f MW",
        tick,
        obs.get("solar_mw", 0),
        obs.get("wind_mw", 0),
        obs.get("demand_mw", 0),
        obs.get("battery_soc_pct", 0),
        obs.get("price_per_kwh", 0),
        obs.get("line_limit_mw", 0),
    )

    if obs.get("active_storm"):
        log.warning(
            "tick=%d  ACTIVE STORM  wind_speed=%.1f m/s",
            tick,
            obs.get("wind_speed_ms", 0),
        )
    if obs.get("storm_alerts"):
        for a in obs["storm_alerts"]:
            log.info(
                "tick=%d  storm_alert id=%s  winds=%.0f m/s  %s–%s",
                tick,
                a.id,
                a.wind_speed_ms,
                a.storm_start,
                a.storm_end,
            )
    if obs.get("maintenance"):
        for m in obs["maintenance"]:
            if m.status in ("pending", "active"):
                log.info(
                    "tick=%d  maintenance id=%s  asset=%s  status=%s  %s–%s",
                    tick,
                    m.id,
                    m.asset,
                    m.status,
                    m.start,
                    m.end,
                )

    if (
        os.environ.get("DATA_SOURCE", "simulator") == "db"
        and _db_project_id is not None
    ):
        # overlay DB events onto simulator observation
        obs = _apply_db_events(obs, tick, _db_project_id)

        log.info(
            "tick=%d  post-events  solar=%.1f MW  wind=%.1f MW  "
            "demand=%.1f MW  line_limit=%.0f MW  active_storm=%s",
            tick,
            obs.get("solar_mw", 0),
            obs.get("wind_mw", 0),
            obs.get("demand_mw", 0),
            obs.get("line_limit_mw", 0),
            obs.get("active_storm", False),
        )

        # asset status masking (trips/restores)
        from graph.asset_status import auto_restore_expired, read_asset_statuses

        auto_restore_expired(_db_project_id, tick)
        statuses = read_asset_statuses(_db_project_id)

        tripped = [s for s in statuses if s["status"] == "tripped"]
        if tripped:
            log.warning(
                "tick=%d  tripped assets: %s",
                tick,
                [(s["asset_type"], s["asset_id"]) for s in tripped],
            )

        obs = _apply_asset_statuses(obs, statuses)
        obs["asset_statuses"] = statuses

        log.info(
            "tick=%d  post-masking  solar=%.1f MW  wind=%.1f MW  "
            "battery_max_discharge=%.1f MW  line_limit=%.0f MW",
            tick,
            obs.get("solar_mw", 0),
            obs.get("wind_mw", 0),
            obs.get("battery_max_discharge_mw", 0),
            obs.get("line_limit_mw", 0),
        )

    return obs
