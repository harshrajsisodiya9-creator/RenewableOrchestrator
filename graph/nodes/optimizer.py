"""LangGraph node: translates strategy into a dispatch plan via LP."""

from __future__ import annotations

from graph.models.state import Action, Forecast, State

DT = 0.25  # hours per tick

# cost constants (₹/MWh)
WEAR_COST = 500.0            # 0.50 ₹/kWh
UNMET_PENALTY = 50_000.0     # 50 ₹/kWh — must always exceed any possible buy cost
SHORTFALL_PENALTY = 5_000.0  # 5 ₹/kWh
TERMINAL_BONUS = 10.0        # ₹/MWh stored at horizon end
TEMPORAL_DISCOUNT = 0.85     # per-interval decay on unmet/shortfall penalties


def _forecast_values(fc: Forecast | None, n: int) -> list[float]:
    if fc is None:
        return [0.0] * n
    vals = fc.values[:n]
    return vals + [0.0] * (n - len(vals))


def _solve_lp(state: State) -> Action | None:
    """Formulate and solve the 6-hour-ahead LP. Returns None on failure."""
    try:
        from scipy.optimize import linprog
        import numpy as np
    except ImportError:
        return None

    N = 24  # forecast horizon intervals

    solar_fc = _forecast_values(state.get("solar_forecast"), N)
    wind_fc = _forecast_values(state.get("wind_forecast"), N)
    demand_fc = _forecast_values(state.get("demand_forecast"), N)
    price_fc = _forecast_values(state.get("price_forecast"), N)

    # use actuals for interval 0
    solar_fc[0] = state.get("solar_mw", solar_fc[0])
    wind_fc[0] = state.get("wind_mw", wind_fc[0])
    demand_fc[0] = state.get("demand_mw", demand_fc[0])
    price_fc[0] = state.get("price_per_kwh", price_fc[0])

    # cap forecast prices at grid price cap (forecast noise can exceed it)
    price_cap = 10.0  # ₹/kWh
    price_fc = [min(p, price_cap) for p in price_fc]

    renewables = [solar_fc[t] + wind_fc[t] for t in range(N)]

    # battery parameters
    max_chg = state.get("battery_max_charge_mw", 150.0)
    max_dis = state.get("battery_max_discharge_mw", 150.0)
    e_min = state.get("battery_min_energy_mwh", 40.0)
    e_max = state.get("battery_max_energy_mwh", 360.0)
    e0 = state.get("battery_energy_mwh", 200.0)
    capacity = state.get("battery_capacity_mwh", 400.0)

    line_lim = state.get("line_limit_mw", 150.0)
    reserve_target = state.get("reserve_target_pct", 20.0) / 100.0 * capacity

    buy_premium = 500.0  # 0.50 ₹/kWh in ₹/MWh
    carbon_rate = state.get("carbon_price_per_tonne", 500.0) * 0.71
    curtail_pen = state.get("curtail_penalty_per_kwh", 0.30) * 1000.0

    # variable layout: [charge, discharge, buy, sell, curtail, unmet, shortfall, energy]
    # each block has N entries
    NVARS = 8 * N

    def idx(block: int, t: int) -> int:
        return block * N + t

    # ── objective coefficients ────────────────────────────────────────────
    c = np.zeros(NVARS)
    for t in range(N):
        p_mwh = price_fc[t] * 1000.0  # ₹/kWh → ₹/MWh
        decay = TEMPORAL_DISCOUNT ** t
        c[idx(0, t)] = WEAR_COST * DT                               # charge
        c[idx(1, t)] = WEAR_COST * DT                               # discharge
        c[idx(2, t)] = (p_mwh + buy_premium + carbon_rate) * DT     # buy
        c[idx(3, t)] = -p_mwh * DT                                  # sell (income)
        c[idx(4, t)] = curtail_pen * DT                              # curtail
        c[idx(5, t)] = UNMET_PENALTY * DT * decay                   # unmet
        c[idx(6, t)] = SHORTFALL_PENALTY * DT * decay                # shortfall
    # terminal bonus for stored energy at end of horizon
    c[idx(7, N - 1)] = -TERMINAL_BONUS

    # ── bounds ────────────────────────────────────────────────────────────
    bounds: list[tuple[float, float]] = []
    for t in range(N):
        bounds.append((0, max_chg))                   # charge
    for t in range(N):
        bounds.append((0, max_dis))                    # discharge
    for t in range(N):
        bounds.append((0, line_lim))                   # buy
    for t in range(N):
        bounds.append((0, line_lim))                   # sell
    for t in range(N):
        bounds.append((0, max(0, renewables[t])))      # curtail
    for t in range(N):
        bounds.append((0, max(0, demand_fc[t])))       # unmet
    for t in range(N):
        bounds.append((0, capacity))                   # shortfall
    for t in range(N):
        bounds.append((e_min, e_max))                  # energy

    # ── equality constraints ──────────────────────────────────────────────
    # 1) energy balance:
    #    solar + wind + discharge + buy + unmet = demand + charge + sell + curtail
    #    → -charge + discharge + buy - sell - curtail + unmet = demand - renewables
    # 2) battery dynamics:
    #    energy[t] - charge[t]*dt + discharge[t]*dt = energy[t-1]  (E0 for t=0)

    n_eq = 2 * N
    A_eq = np.zeros((n_eq, NVARS))
    b_eq = np.zeros(n_eq)

    for t in range(N):
        row = t
        A_eq[row, idx(0, t)] = -1   # charge
        A_eq[row, idx(1, t)] = 1    # discharge
        A_eq[row, idx(2, t)] = 1    # buy
        A_eq[row, idx(3, t)] = -1   # sell
        A_eq[row, idx(4, t)] = -1   # curtail
        A_eq[row, idx(5, t)] = 1    # unmet
        b_eq[row] = demand_fc[t] - renewables[t]

    for t in range(N):
        row = N + t
        A_eq[row, idx(7, t)] = 1           # energy[t]
        A_eq[row, idx(0, t)] = -DT         # -charge*dt
        A_eq[row, idx(1, t)] = DT          # +discharge*dt
        if t == 0:
            b_eq[row] = e0
        else:
            A_eq[row, idx(7, t - 1)] = -1  # -energy[t-1]
            b_eq[row] = 0

    # ── inequality constraints ────────────────────────────────────────────
    # reserve floor: energy[t] + shortfall[t] >= reserve_target
    # →  -energy[t] - shortfall[t] <= -reserve_target
    A_ub = np.zeros((N, NVARS))
    b_ub = np.zeros(N)
    for t in range(N):
        A_ub[t, idx(7, t)] = -1
        A_ub[t, idx(6, t)] = -1
        b_ub[t] = -reserve_target

    # ── solve ─────────────────────────────────────────────────────────────
    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                     bounds=bounds, method="highs",
                     options={"presolve": True, "time_limit": 2.0})

    if not result.success:
        return None

    x = result.x
    return Action(
        charge=round(float(x[idx(0, 0)]), 2),
        discharge=round(float(x[idx(1, 0)]), 2),
        buy=round(float(x[idx(2, 0)]), 2),
        sell=round(float(x[idx(3, 0)]), 2),
        curtail=round(float(x[idx(4, 0)]), 2),
        unmet=round(float(x[idx(5, 0)]), 2),
    )


def _fallback_dispatch(state: State) -> Action:
    """Simple rule-based dispatch when LP is unavailable or infeasible."""
    solar = state.get("solar_mw", 0.0)
    wind = state.get("wind_mw", 0.0)
    demand = state.get("demand_mw", 0.0)
    max_chg = state.get("battery_max_charge_mw", 150.0)
    max_dis = state.get("battery_max_discharge_mw", 150.0)
    line_lim = state.get("line_limit_mw", 150.0)
    e_now = state.get("battery_energy_mwh", 200.0)
    e_min = state.get("battery_min_energy_mwh", 40.0)
    e_max = state.get("battery_max_energy_mwh", 360.0)

    renewables = solar + wind
    gap = demand - renewables

    charge = discharge = buy = sell = curtail = unmet = 0.0

    if gap <= 0:
        surplus = -gap
        charge = min(surplus, max_chg, (e_max - e_now) / DT)
        surplus -= charge
        sell = min(surplus, line_lim)
        surplus -= sell
        curtail = surplus
    else:
        deficit = gap
        avail_discharge = min(max_dis, (e_now - e_min) / DT)
        discharge = min(deficit, avail_discharge)
        deficit -= discharge
        buy = min(deficit, line_lim)
        deficit -= buy
        unmet = max(0, deficit)

    return Action(
        charge=round(charge, 2),
        discharge=round(discharge, 2),
        buy=round(buy, 2),
        sell=round(sell, 2),
        curtail=round(curtail, 2),
        unmet=round(unmet, 2),
    )


def optimizer(state: State) -> dict:
    plan = _solve_lp(state)
    if plan is not None:
        return {"plan": plan, "plan_status": "optimal"}
    plan = _fallback_dispatch(state)
    return {"plan": plan, "plan_status": "fallback"}
