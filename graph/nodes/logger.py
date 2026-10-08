"""LangGraph node: records the tick's full snapshot into tick_log."""

from __future__ import annotations

from graph.models.state import Action, State

DT = 0.25
EMISSION_TCO2_PER_MWH = 0.71


def logger(state: State) -> dict:
    action: Action = state.get("validated_action", Action())
    price = state.get("price_per_kwh", 0.0)
    buy_premium = 0.50

    buy_cost = action.buy * DT * (price + buy_premium) * 1000.0
    sell_income = action.sell * DT * price * 1000.0
    carbon = action.buy * DT * EMISSION_TCO2_PER_MWH

    entry = {
        "tick": state.get("tick", 0),
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
    }

    existing = list(state.get("tick_log", []))
    existing.append(entry)
    return {"tick_log": existing}
