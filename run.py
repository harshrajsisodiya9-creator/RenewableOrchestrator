"""Run a full 24-hour simulation of the Renewable Energy Orchestrator."""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from graph.simulator import Simulator, load_config
from graph.nodes.data_collector import init_simulator, init_data_collector_db
from graph.nodes.executor import init_executor_simulator
from graph.nodes.monitor import reset_monitor
from graph.graph import graph
from graph.models.state import Action

TICKS = 96


def run(world_yaml: str = "config/world.yaml",
        scenario_yaml: str = "config/scenarios/may_storm.yaml",
        project_name: str | None = None) -> list[dict]:

    data_source = os.environ.get("DATA_SOURCE", "simulator")
    project_id: int | None = None

    if data_source == "db":
        from graph.db_config_loader import load_config_from_db
        from graph.asset_status import seed_asset_statuses
        from graph.run_state import run_state

        cfg = load_config_from_db(project_name or "farm 1")
        project_id = cfg.pop("_project_id")

        seed_asset_statuses(
            project_id,
            [f["id"] for f in cfg["solar_farms"]],
            [f["id"] for f in cfg["wind_farms"]],
            [b["id"] for b in cfg.get("battery_ids", [])],
        )
        run_state.set_running(project_id)
    else:
        cfg = load_config(world_yaml, scenario_yaml)

    sim = Simulator(cfg)
    init_simulator(sim)
    init_executor_simulator(sim)
    reset_monitor()

    if data_source == "db" and project_id is not None:
        init_data_collector_db(
            project_id, cfg["solar_farms"], cfg["wind_farms"]
        )

    defaults = cfg.get("defaults", {})
    state: dict = {
        "mode": defaults.get("mode", "reliability"),
        "reserve_floor_pct": defaults.get("reserve_floor_pct", 20.0),
        "carbon_price_per_tonne": defaults.get("carbon_price_per_tonne", 500.0),
        "curtail_penalty_per_kwh": defaults.get("curtail_penalty_per_kwh", 0.30),
        "tick_log": [],
        "retry_count": 0,
    }

    for tick in range(TICKS):
        if data_source == "db":
            run_state.set_tick(tick)
        state["tick"] = tick
        state["retry_count"] = 0
        state["violations"] = []
        result = graph.invoke(state)
        state.update(result)

    if data_source == "db":
        run_state.set_stopped()

    return state.get("tick_log", [])


def print_scorecard(log: list[dict]) -> None:
    if not log:
        print("No tick data recorded.")
        return

    total_demand = sum(e["demand_mw"] for e in log) * 0.25
    total_solar = sum(e["solar_mw"] for e in log) * 0.25
    total_wind = sum(e["wind_mw"] for e in log) * 0.25
    total_buy = sum(e["buy_mw"] for e in log) * 0.25
    total_sell = sum(e["sell_mw"] for e in log) * 0.25
    total_curtail = sum(e["curtail_mw"] for e in log) * 0.25
    total_unmet = sum(e["unmet_mw"] for e in log) * 0.25
    total_charge = sum(e["charge_mw"] for e in log) * 0.25
    total_discharge = sum(e["discharge_mw"] for e in log) * 0.25
    total_cost = sum(e["cash_cost_inr"] for e in log)
    total_carbon = sum(e["carbon_tonnes"] for e in log)
    supervisor_calls = sum(1 for e in log if e["supervisor_called"])
    violation_ticks = sum(1 for e in log if not e["validation_passed"])

    served = total_demand - total_unmet
    reliability = served / total_demand * 100 if total_demand else 100

    print("\n" + "=" * 60)
    print("  RENEWABLE ENERGY ORCHESTRATOR — DAY SCORECARD")
    print("=" * 60)
    print(f"  Demand served:     {served:8.1f} MWh  ({reliability:.1f} %)")
    print(f"  Total demand:      {total_demand:8.1f} MWh")
    print(f"  Unmet demand:      {total_unmet:8.1f} MWh")
    print(f"  Solar generated:   {total_solar:8.1f} MWh")
    print(f"  Wind generated:    {total_wind:8.1f} MWh")
    print(f"  Grid purchased:    {total_buy:8.1f} MWh")
    print(f"  Grid sold:         {total_sell:8.1f} MWh")
    print(f"  Curtailed:         {total_curtail:8.1f} MWh")
    print(f"  Battery charged:   {total_charge:8.1f} MWh")
    print(f"  Battery discharged:{total_discharge:8.1f} MWh")
    print("-" * 60)
    print(f"  Total cost:        ₹{total_cost:,.0f}")
    print(f"  Carbon emitted:    {total_carbon:.2f} tCO₂")
    print(f"  Supervisor calls:  {supervisor_calls} / {len(log)}")
    print(f"  Violation ticks:   {violation_ticks} / {len(log)}")
    print("=" * 60)


def save_results(log: list[dict], out_dir: str = "outputs") -> None:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "day_log.json")
    with open(path, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"\nResults saved to {path}")


if __name__ == "__main__":
    log = run()
    print_scorecard(log)
    save_results(log)
