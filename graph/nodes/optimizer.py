"""LangGraph node: translates strategy into a dispatch plan via LP."""

from __future__ import annotations

import logging
import time

from graph.models.state import Action, DayPlan, Forecast, State

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("optimizer")

DT = 0.25  # hours per tick

# ── cost / config constants ──────────────────────────────────────────────
GRID_FEE = 0.50  # ₹/kWh — grid surcharge on purchases (= buy_premium_per_kwh)
CYCLE_COST = 100.0  # ₹/MWh — battery cycling cost
RAMP_COST = 50.0  # ₹/MW — penalty per MW of grid-import ramp
ETA_D = 0.90  # discharge efficiency for terminal valuation

UNMET_PENALTY = 100_000.0  # ₹/MWh — reliability dominates all cost terms
SHORTFALL_PENALTY = 1_000.0  # ₹/MWh — soft reserve floor, low enough to violate when unmet is inevitable


def _forecast_values(fc: Forecast | None, n: int) -> list[float]:
    if fc is None:
        return [0.0] * n
    vals = fc.values[:n]
    return vals + [0.0] * (n - len(vals))


def _floor_pct_at_tick(abs_tick: int, plan: DayPlan) -> float:
    """Return the floor percentage for the given absolute tick (0–95)."""
    h = abs_tick // 4
    m = (abs_tick % 4) * 15
    t_str = f"{h:02d}:{m:02d}"
    for w in plan.floor_schedule:
        if w.start <= t_str < w.end:
            return w.floor_pct
    return 35.0


def _solve_lp(state: State) -> tuple[Action | None, dict]:
    """Formulate and solve the 24-hour rolling LP. Returns (Action, info) or (None, info)."""
    try:
        import numpy as np
        from scipy.optimize import linprog
    except ImportError:
        log.error("scipy/numpy not available — LP solver unavailable")
        return None, {}

    tick = state.get("tick", 0)
    N = max(4, 96 - tick)  # horizon covers remaining day only

    solar_fc = _forecast_values(state.get("solar_forecast"), N)
    wind_fc = _forecast_values(state.get("wind_forecast"), N)
    demand_fc = _forecast_values(state.get("demand_forecast"), N)
    price_fc = _forecast_values(state.get("price_forecast"), N)

    # use actuals for interval 0
    solar_fc[0] = state.get("solar_mw", solar_fc[0])
    wind_fc[0] = state.get("wind_mw", wind_fc[0])
    demand_fc[0] = state.get("demand_mw", demand_fc[0])
    price_fc[0] = state.get("price_per_kwh", price_fc[0])

    price_cap = 10.0  # ₹/kWh
    price_fc = [min(p, price_cap) for p in price_fc]

    renewables = [solar_fc[t] + wind_fc[t] for t in range(N)]

    # battery parameters
    max_chg = state.get("battery_max_charge_mw", 0.0)
    max_dis = state.get("battery_max_discharge_mw", 0.0)
    e_min = state.get("battery_min_energy_mwh", 0.0)
    e_max = state.get("battery_max_energy_mwh", 0.0)
    e0 = state.get("battery_energy_mwh", 0.0)
    capacity = state.get("battery_capacity_mwh", 0.0)

    line_lim = state.get("line_limit_mw", 0.0)
    line_lim_nominal = state.get("line_limit_nominal_mw", line_lim)
    prev_buy = state.get("prev_buy_mw", 0.0)

    # ── per-tick line limit (storm derating) ─────────────────────────────
    line_lim_per_tick = [line_lim_nominal] * N
    storm_alerts = state.get("storm_alerts", [])
    for alert in storm_alerts:
        try:
            sh, sm = map(int, alert.storm_start.split(":")[:2])
            eh, em = map(int, alert.storm_end.split(":")[:2])
            storm_start_tick = sh * 4 + sm // 15
            storm_end_tick = eh * 4 + em // 15
            for k in range(N):
                abs_t = tick + k
                if abs_t < 96 and storm_start_tick <= abs_t < storm_end_tick:
                    line_lim_per_tick[k] = min(line_lim_per_tick[k], alert.line_limit_mw)
        except (ValueError, AttributeError):
            pass
    line_lim_per_tick[0] = min(line_lim_per_tick[0], line_lim)  # k=0 uses actual current limit

    # ── day plan: time-varying floor + sell policy ────────────────────────
    day_plan: DayPlan = state.get("day_plan", DayPlan())
    sell_policy = day_plan.sell_policy

    floor_mwh = []
    for k in range(N):
        abs_t = tick + k
        if abs_t < 96:
            fpct = _floor_pct_at_tick(abs_t, day_plan)
        else:
            fpct = 35.0
        floor_mwh.append(fpct / 100.0 * capacity)

    # ── features: peak ticks, e_need, terminal values ────────────────────
    features = state.get("features", {})
    # peak_ticks from features are forecast-relative indices (same frame as LP)
    peak_ticks = features.get("peak_ticks", [])
    if not peak_ticks:
        peak_ticks = list(range(N))

    e_need = features.get("e_need_mwh", 0.0)

    # terminal value tiers
    peak_prices = [price_fc[k] for k in peak_ticks if k < len(price_fc)]
    mean_peak_price = sum(peak_prices) / len(peak_prices) if peak_prices else 3.0
    min_all_price = min(price_fc) if price_fc else 1.0

    v_high = (mean_peak_price + GRID_FEE) * 1000.0 * ETA_D  # ₹/MWh
    v_low = (min_all_price + GRID_FEE) * 1000.0 * ETA_D  # ₹/MWh

    # ── sell policy bounds ────────────────────────────────────────────────
    sell_upper = [0.0] * N
    if sell_policy == "free":
        sell_upper = [line_lim_per_tick[k] for k in range(N)]
    elif sell_policy == "only_above_terminal":
        for k in range(N):
            if price_fc[k] * 1000.0 > v_high:
                sell_upper[k] = line_lim_per_tick[k]
    # "no_sell" → all zeros (already initialised)

    carbon_rate = state.get("carbon_price_per_tonne", 500.0) * 0.71
    curtail_pen = state.get("curtail_penalty_per_kwh", 0.30) * 1000.0

    log.info(
        "tick=%d  LP inputs  N=%d  solar[0]=%.1f MW  wind[0]=%.1f MW  demand[0]=%.1f MW  "
        "price[0]=%.2f ₹/kWh  battery=%.1f/%.0f MWh  max_chg=%.0f MW  max_dis=%.0f MW  "
        "line=%.0f/%.0f MW  floor[0]=%.1f MWh  sell_policy=%s  v_high=%.0f  v_low=%.0f  e_need=%.1f",
        tick, N,
        solar_fc[0], wind_fc[0], demand_fc[0], price_fc[0],
        e0, capacity, max_chg, max_dis, line_lim, line_lim_nominal,
        floor_mwh[0], sell_policy, v_high, v_low, e_need,
    )

    # ── variable layout ──────────────────────────────────────────────────
    # blocks: charge discharge buy sell curtail unmet shortfall energy ramp_up ramp_down
    # then: s1 s2 (terminal tier split)
    NBLOCKS = 10
    NVARS = NBLOCKS * N + 2
    IDX_S1 = NBLOCKS * N
    IDX_S2 = NBLOCKS * N + 1

    def idx(block: int, t: int) -> int:
        return block * N + t

    # ── objective coefficients ───────────────────────────────────────────
    c = np.zeros(NVARS)
    for t in range(N):
        p_mwh = price_fc[t] * 1000.0
        c[idx(0, t)] = CYCLE_COST * DT  # charge
        c[idx(1, t)] = CYCLE_COST * DT  # discharge
        c[idx(2, t)] = (p_mwh + GRID_FEE * 1000.0 + carbon_rate) * DT  # buy
        c[idx(3, t)] = -p_mwh * DT  # sell (income)
        c[idx(4, t)] = curtail_pen * DT  # curtail
        urgency = 0.995 ** t  # gentle time preference: earlier unmet costs slightly more
        c[idx(5, t)] = UNMET_PENALTY * DT * urgency  # unmet
        c[idx(6, t)] = SHORTFALL_PENALTY * DT * urgency  # shortfall
        c[idx(8, t)] = RAMP_COST  # ramp_up
        c[idx(9, t)] = RAMP_COST  # ramp_down

    # terminal value (subtracted from cost → incentivises stored energy)
    c[IDX_S1] = -v_high
    c[IDX_S2] = -v_low

    # ── bounds ───────────────────────────────────────────────────────────
    bounds: list[tuple[float, float]] = []
    for t in range(N):
        bounds.append((0, max_chg))  # charge
    for t in range(N):
        bounds.append((0, max_dis))  # discharge
    for t in range(N):
        bounds.append((0, line_lim_per_tick[t]))  # buy (storm-derated)
    for t in range(N):
        bounds.append((0, sell_upper[t]))  # sell (policy-limited)
    for t in range(N):
        bounds.append((0, max(0, renewables[t])))  # curtail
    for t in range(N):
        bounds.append((0, max(0, demand_fc[t])))  # unmet
    for t in range(N):
        bounds.append((0, capacity))  # shortfall
    for t in range(N):
        bounds.append((e_min, e_max))  # energy
    for t in range(N):
        bounds.append((0, line_lim_per_tick[t]))  # ramp_up
    for t in range(N):
        bounds.append((0, line_lim_per_tick[t]))  # ramp_down
    # terminal split variables
    bounds.append((0, max(0, e_need)))  # s1: high-value tier
    bounds.append((0, capacity))  # s2: low-value tier

    # ── equality constraints ─────────────────────────────────────────────
    # 1) energy balance (N rows)
    # 2) battery dynamics (N rows)
    # 3) ramp decomposition (N rows): buy[t] - buy[t-1] = ramp_up[t] - ramp_down[t]
    # 4) terminal SoC split (1 row): energy[N-1] - floor_mwh[N-1] = s1 + s2
    n_eq = 3 * N + 1
    A_eq = np.zeros((n_eq, NVARS))
    b_eq = np.zeros(n_eq)

    for t in range(N):
        # energy balance: -charge + discharge + buy - sell - curtail + unmet = demand - renewables
        row = t
        A_eq[row, idx(0, t)] = -1   # charge
        A_eq[row, idx(1, t)] = 1    # discharge
        A_eq[row, idx(2, t)] = 1    # buy
        A_eq[row, idx(3, t)] = -1   # sell
        A_eq[row, idx(4, t)] = -1   # curtail
        A_eq[row, idx(5, t)] = 1    # unmet
        b_eq[row] = demand_fc[t] - renewables[t]

    for t in range(N):
        # battery dynamics: energy[t] - charge[t]*DT + discharge[t]*DT = energy[t-1]
        row = N + t
        A_eq[row, idx(7, t)] = 1    # energy[t]
        A_eq[row, idx(0, t)] = -DT  # -charge*DT
        A_eq[row, idx(1, t)] = DT   # +discharge*DT
        if t == 0:
            b_eq[row] = e0
        else:
            A_eq[row, idx(7, t - 1)] = -1  # -energy[t-1]
            b_eq[row] = 0

    for t in range(N):
        # ramp: buy[t] - buy[t-1] - ramp_up[t] + ramp_down[t] = 0
        row = 2 * N + t
        A_eq[row, idx(2, t)] = 1     # buy[t]
        A_eq[row, idx(8, t)] = -1    # -ramp_up[t]
        A_eq[row, idx(9, t)] = 1     # +ramp_down[t]
        if t == 0:
            b_eq[row] = prev_buy
        else:
            A_eq[row, idx(2, t - 1)] = -1  # -buy[t-1]
            b_eq[row] = 0

    # terminal SoC split: energy[N-1] - s1 - s2 = e_min  (always feasible)
    row_term = 3 * N
    A_eq[row_term, idx(7, N - 1)] = 1
    A_eq[row_term, IDX_S1] = -1
    A_eq[row_term, IDX_S2] = -1
    b_eq[row_term] = e_min

    # ── inequality constraints ───────────────────────────────────────────
    # reserve floor: -energy[t] - shortfall[t] <= -floor_mwh[t]
    A_ub = np.zeros((N, NVARS))
    b_ub = np.zeros(N)
    for t in range(N):
        A_ub[t, idx(7, t)] = -1
        A_ub[t, idx(6, t)] = -1
        b_ub[t] = -floor_mwh[t]

    # ── solve ────────────────────────────────────────────────────────────
    log.debug(
        "tick=%d  LP formulation: %d vars, %d eq constraints, %d ub constraints",
        tick, NVARS, n_eq, N,
    )

    t0 = time.monotonic()
    result = linprog(
        c,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
        options={"presolve": True, "time_limit": 5.0},
    )
    solve_ms = (time.monotonic() - t0) * 1000

    info = {
        "terminal_v_high": round(v_high, 1),
        "terminal_v_low": round(v_low, 1),
        "e_need_mwh": round(e_need, 1),
        "solve_ms": round(solve_ms, 1),
    }

    if not result.success:
        log.warning(
            "tick=%d  LP failed  status=%d  message=%s",
            tick, result.status, result.message,
        )
        return None, info

    log.info(
        "tick=%d  LP solved  obj=%.0f  iterations=%d  solve=%.1fms",
        tick, result.fun, result.nit, solve_ms,
    )

    x = result.x

    return Action(
        charge=round(float(x[idx(0, 0)]), 2),
        discharge=round(float(x[idx(1, 0)]), 2),
        buy=round(float(x[idx(2, 0)]), 2),
        sell=round(float(x[idx(3, 0)]), 2),
        curtail=round(float(x[idx(4, 0)]), 2),
        unmet=round(float(x[idx(5, 0)]), 2),
    ), info


def _fallback_dispatch(state: State) -> Action:
    """Simple rule-based dispatch when LP is unavailable or infeasible."""
    tick = state.get("tick", 0)
    solar = state.get("solar_mw", 0.0)
    wind = state.get("wind_mw", 0.0)
    demand = state.get("demand_mw", 0.0)
    max_chg = state.get("battery_max_charge_mw", 0.0)
    max_dis = state.get("battery_max_discharge_mw", 0.0)
    line_lim = state.get("line_limit_mw", 0.0)
    e_now = state.get("battery_energy_mwh", 0.0)
    e_min = state.get("battery_min_energy_mwh", 0.0)
    e_max = state.get("battery_max_energy_mwh", 0.0)

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

    action = Action(
        charge=round(charge, 2),
        discharge=round(discharge, 2),
        buy=round(buy, 2),
        sell=round(sell, 2),
        curtail=round(curtail, 2),
        unmet=round(unmet, 2),
    )
    log.info(
        "tick=%d  FALLBACK dispatch  charge=%.1f  discharge=%.1f  buy=%.1f  "
        "sell=%.1f  curtail=%.1f  unmet=%.1f MW",
        tick,
        action.charge, action.discharge, action.buy,
        action.sell, action.curtail, action.unmet,
    )
    return action


def optimizer(state: State) -> dict:
    tick = state.get("tick", 0)
    plan, info = _solve_lp(state)
    if plan is not None:
        log.info(
            "tick=%d  OPTIMAL dispatch  charge=%.1f  discharge=%.1f  buy=%.1f  "
            "sell=%.1f  curtail=%.1f  unmet=%.1f MW",
            tick,
            plan.charge, plan.discharge, plan.buy,
            plan.sell, plan.curtail, plan.unmet,
        )
        return {"plan": plan, "plan_status": "optimal", "lp_info": info}
    log.warning("tick=%d  LP failed, using fallback dispatch", tick)
    plan = _fallback_dispatch(state)
    return {"plan": plan, "plan_status": "fallback", "lp_info": info}
