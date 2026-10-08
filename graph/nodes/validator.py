"""LangGraph node: clips the optimizer's plan to physical limits."""

from __future__ import annotations

from dataclasses import asdict

from graph.models.state import Action, State, Violation

DT = 0.25  # hours per tick


def validator(state: State) -> dict:
    plan: Action = state.get("plan", Action())
    solar = state.get("solar_mw", 0.0)
    wind = state.get("wind_mw", 0.0)
    demand = state.get("demand_mw", 0.0)
    max_chg = state.get("battery_max_charge_mw", 150.0)
    max_dis = state.get("battery_max_discharge_mw", 150.0)
    e_now = state.get("battery_energy_mwh", 200.0)
    e_min = state.get("battery_min_energy_mwh", 40.0)
    e_max = state.get("battery_max_energy_mwh", 360.0)
    line_lim = state.get("line_limit_mw", 150.0)
    renewables = solar + wind

    violations: list[Violation] = []
    charge = plan.charge
    discharge = plan.discharge
    buy = plan.buy
    sell = plan.sell
    curtail = plan.curtail
    unmet = plan.unmet

    def clip(field: str, val: float, lo: float, hi: float,
             limit_name: str) -> float:
        clamped = max(lo, min(hi, val))
        if abs(clamped - val) > 0.01:
            violations.append(Violation(
                field=field, proposed=round(val, 2),
                corrected=round(clamped, 2), limit=round(hi, 2),
                detail=f"{field} clipped from {val:.2f} to {clamped:.2f} "
                       f"({limit_name}={hi:.2f})",
            ))
        return clamped

    # 1. clip negatives
    charge = clip("charge", charge, 0, float("inf"), "non_negative")
    discharge = clip("discharge", discharge, 0, float("inf"), "non_negative")
    buy = clip("buy", buy, 0, float("inf"), "non_negative")
    sell = clip("sell", sell, 0, float("inf"), "non_negative")
    curtail = clip("curtail", curtail, 0, float("inf"), "non_negative")
    unmet = clip("unmet", unmet, 0, float("inf"), "non_negative")

    # 2. resolve simultaneous charge + discharge
    if charge > 0 and discharge > 0:
        net = discharge - charge
        old_c, old_d = charge, discharge
        if net >= 0:
            charge, discharge = 0.0, net
        else:
            charge, discharge = -net, 0.0
        if abs(old_c - charge) > 0.01 or abs(old_d - discharge) > 0.01:
            violations.append(Violation(
                field="charge/discharge", proposed=round(old_c, 2),
                corrected=round(charge, 2), limit=0,
                detail=f"Resolved simultaneous charge={old_c:.1f} & "
                       f"discharge={old_d:.1f} to net",
            ))

    # 3. clip discharge to available energy
    max_dis_energy = max(0, (e_now - e_min) / DT)
    discharge = clip("discharge", discharge, 0, min(max_dis, max_dis_energy),
                      "battery_discharge_limit")

    # 4. clip charge to available headroom
    max_chg_energy = max(0, (e_max - e_now) / DT)
    charge = clip("charge", charge, 0, min(max_chg, max_chg_energy),
                   "battery_charge_limit")

    # 5. clip buy and sell to line limit
    buy = clip("buy", buy, 0, line_lim, "line_limit_mw")
    sell = clip("sell", sell, 0, line_lim, "line_limit_mw")

    # 6. clip curtail to renewables
    curtail = clip("curtail", curtail, 0, renewables, "renewables_mw")

    # 7. rebalance
    supply = renewables + discharge + buy + unmet
    consume = demand + charge + sell + curtail
    imbalance = supply - consume

    if imbalance > 0.01:
        excess = imbalance
        # reduce buy
        red = min(excess, buy)
        buy -= red; excess -= red
        # reduce discharge
        red = min(excess, discharge)
        discharge -= red; excess -= red
        # increase charge (up to limits)
        headroom = min(max_chg, max(0, (e_max - e_now) / DT)) - charge
        inc = min(excess, max(0, headroom))
        charge += inc; excess -= inc
        # increase sell (up to line limit)
        inc = min(excess, max(0, line_lim - sell))
        sell += inc; excess -= inc
        # increase curtail
        inc = min(excess, max(0, renewables - curtail))
        curtail += inc; excess -= inc

    elif imbalance < -0.01:
        deficit = -imbalance
        # reduce sell
        red = min(deficit, sell)
        sell -= red; deficit -= red
        # reduce charge
        red = min(deficit, charge)
        charge -= red; deficit -= red
        # reduce curtail
        red = min(deficit, curtail)
        curtail -= red; deficit -= red
        # increase buy (up to line limit)
        inc = min(deficit, max(0, line_lim - buy))
        buy += inc; deficit -= inc
        # increase discharge (up to limits)
        dis_headroom = min(max_dis, max(0, (e_now - e_min) / DT)) - discharge
        inc = min(deficit, max(0, dis_headroom))
        discharge += inc; deficit -= inc
        # unmet
        if deficit > 0.01:
            unmet += deficit

    validated = Action(
        charge=round(charge, 2),
        discharge=round(discharge, 2),
        buy=round(buy, 2),
        sell=round(sell, 2),
        curtail=round(curtail, 2),
        unmet=round(unmet, 2),
    )

    passed = len(violations) == 0
    retry = state.get("retry_count", 0)

    return {
        "validated_action": validated,
        "validation_passed": passed,
        "violations": violations,
        "retry_count": retry,
    }
