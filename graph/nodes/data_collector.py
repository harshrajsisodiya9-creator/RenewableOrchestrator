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


def init_simulator(sim: Simulator) -> None:
    """Call once at startup to inject the shared Simulator instance."""
    global _simulator
    _simulator = sim


def init_data_collector_db(
    project_id: int,
    solar_farms: list[dict],
    wind_farms: list[dict],
) -> None:
    """Call once at startup in DB mode to provide farm configs for masking."""
    global _db_project_id, _db_solar_farms, _db_wind_farms
    _db_project_id = project_id
    _db_solar_farms = solar_farms
    _db_wind_farms = wind_farms


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
