"""LangGraph node: applies the validated action and updates battery state."""

from __future__ import annotations

from graph.models.state import Action, State

DT = 0.25  # hours per tick
EMISSION_TCO2_PER_MWH = 0.71

_simulator = None


def init_executor_simulator(sim) -> None:
    """Inject the shared Simulator so the executor can update battery state."""
    global _simulator
    _simulator = sim


def executor(state: State) -> dict:
    action: Action = state.get("validated_action", Action())

    e_before = state.get("battery_energy_mwh", 200.0)
    capacity = state.get("battery_capacity_mwh", 400.0)
    price = state.get("price_per_kwh", 3.0)
    buy_premium = 0.50  # ₹/kWh

    # update battery
    delta_mwh = (action.charge - action.discharge) * DT
    if _simulator is not None:
        _simulator.update_battery(delta_mwh)
        e_after = _simulator._battery_energy
    else:
        e_min = state.get("battery_min_energy_mwh", 40.0)
        e_max = state.get("battery_max_energy_mwh", 360.0)
        e_after = max(e_min, min(e_max, e_before + delta_mwh))

    soc_after = (e_after / capacity * 100.0) if capacity > 0 else 0.0

    # financials (₹): energy in MWh = MW × 0.25h, price in ₹/kWh, × 1000 kW/MW
    buy_cost = action.buy * DT * (price + buy_premium) * 1000.0
    sell_income = action.sell * DT * price * 1000.0
    cash_cost = buy_cost - sell_income

    # carbon (tonnes CO2)
    carbon = action.buy * DT * EMISSION_TCO2_PER_MWH

    return {
        "battery_energy_mwh": round(e_after, 2),
        "battery_soc_pct": round(soc_after, 2),
        "prev_buy_mw": action.buy,
    }
