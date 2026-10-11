"""LangGraph node: records the tick's full snapshot into tick_log and appends to a .jsonl file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from graph.models.state import Action, State

DT = 0.25
EMISSION_TCO2_PER_MWH = 0.71
LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def logger(state: State) -> dict:
    action: Action = state.get("validated_action", Action())
    price = state.get("price_per_kwh", 0.0)
    buy_premium = 0.50

    buy_cost = action.buy * DT * (price + buy_premium) * 1000.0
    sell_income = action.sell * DT * price * 1000.0
    carbon = action.buy * DT * EMISSION_TCO2_PER_MWH

    day_plan = state.get("day_plan")
    lp_info = state.get("lp_info", {})

    # active floor from day plan
    tick_val = state.get("tick", 0)
    active_floor_pct = 35.0
    if day_plan is not None:
        h = tick_val // 4
        m = (tick_val % 4) * 15
        t_str = f"{h:02d}:{m:02d}"
        for w in day_plan.floor_schedule:
            if w.start <= t_str < w.end:
                active_floor_pct = w.floor_pct
                break

    entry = {
        "tick": tick_val,
        "timestamp": state.get("timestamp", ""),
        "solar_mw": state.get("solar_mw", 0.0),
        "wind_mw": state.get("wind_mw", 0.0),
        "renewables_mw": state.get("renewables_mw", 0.0),
        "demand_mw": state.get("demand_mw", 0.0),
        "price_per_kwh": price,
        "charge_mw": action.charge,
        "discharge_mw": action.discharge,
        "buy_mw": action.buy,
        "sell_mw": action.sell,
        "curtail_mw": action.curtail,
        "unmet_mw": action.unmet,
        "battery_soc_pct": state.get("battery_soc_pct", 0.0),
        "battery_energy_mwh": state.get("battery_energy_mwh", 0.0),
        "risk_level": state.get("risk_level", ""),
        "strategy_reason": state.get("strategy_reason", ""),
        "plan_status": state.get("plan_status", ""),
        "validation_passed": state.get("validation_passed", True),
        "violations": [v.detail for v in state.get("violations", [])],
        "cash_cost_inr": round(buy_cost - sell_income, 2),
        "carbon_tonnes": round(carbon, 4),
        "supervisor_called": state.get("should_call_supervisor", False),
        # ── new fields (Change 5) ────────────────────────────────────────
        "planner_called": state.get("planner_called", False),
        "day_plan_summary": day_plan.summary if day_plan else "",
        "active_floor_pct": active_floor_pct,
        "sell_policy": day_plan.sell_policy if day_plan else "",
        "terminal_v_high": lp_info.get("terminal_v_high", 0.0),
        "terminal_v_low": lp_info.get("terminal_v_low", 0.0),
        "e_need_mwh": lp_info.get("e_need_mwh", 0.0),
        "llm_fallback_used": state.get("llm_fallback_used", False),
    }

    _write_to_file(state, entry)

    existing = list(state.get("tick_log", []))
    existing.append(entry)
    return {"tick_log": existing}


def _write_to_file(state: State, entry: dict) -> None:
    project_id = state.get("project_id", "unknown")
    session_id = state.get("session_id", "unknown")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / f"project_{project_id}_session_{session_id}.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
