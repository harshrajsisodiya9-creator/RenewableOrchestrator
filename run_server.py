"""Combined launcher: FastAPI server + graph simulation loop."""

from __future__ import annotations

import os
import threading
import time

from dotenv import load_dotenv
load_dotenv()

import uvicorn

from api.main import app
from graph.run_state import run_state


def run_graph_loop(project_name: str) -> None:
    from graph.simulator import Simulator, load_config
    from graph.nodes.data_collector import init_simulator, init_data_collector_db
    from graph.nodes.executor import init_executor_simulator
    from graph.nodes.monitor import reset_monitor
    from graph.graph import graph
    from run import print_scorecard

    data_source = os.environ.get("DATA_SOURCE", "simulator")
    project_id: int | None = None

    if data_source == "db":
        from graph.db_config_loader import load_config_from_db
        from graph.asset_status import seed_asset_statuses

        cfg = load_config_from_db(project_name)
        project_id = cfg.pop("_project_id")

        seed_asset_statuses(
            project_id,
            [f["id"] for f in cfg["solar_farms"]],
            [f["id"] for f in cfg["wind_farms"]],
            [b["id"] for b in cfg.get("battery_ids", [])],
        )
        run_state.set_running(project_id)
    else:
        cfg = load_config("config/world.yaml", "config/scenarios/may_storm.yaml")

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

    for tick in range(96):
        run_state.set_tick(tick)
        state["tick"] = tick
        state["retry_count"] = 0
        state["violations"] = []
        result = graph.invoke(state)
        state.update(result)

    run_state.set_stopped()
    print_scorecard(state.get("tick_log", []))


@app.get("/status")
def get_status():
    return {
        "running": run_state.running,
        "current_tick": run_state.get_tick(),
        "project_id": run_state.project_id,
    }


@app.post("/start")
def start_simulation(project_name: str = "farm 1"):
    if run_state.running:
        return {"error": "Simulation already running"}
    thread = threading.Thread(
        target=run_graph_loop, args=(project_name,), daemon=True
    )
    thread.start()
    return {"status": "started", "project_name": project_name, "ticks": 96}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
