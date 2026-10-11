"""LangGraph node: strategic brain — sets risk level and reserve targets."""

from __future__ import annotations

import json
import os

from graph.models.state import DayPlan, State

_MODE_RESERVE: dict[str, float] = {
    "reliability": 35.0,
    "profit": 10.0,
    "clean": 20.0,
}

_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}

SYSTEM_PROMPT = """\
You are the strategic supervisor of a renewable-energy microgrid.

Your job: assess the current grid situation and set the operating strategy
for the next interval.  You MUST respond with ONLY a JSON object (no
markdown, no commentary) with exactly these keys:

  risk_level: one of "low", "medium", "high", "critical"
  reserve_target_pct: float 0 to 100, battery reserve floor (% of capacity)
  strategy_reason: one sentence explaining your decision
  request_replan: boolean — set true ONLY if you believe the day plan \
itself is wrong and needs to be regenerated; otherwise false

You receive the active day plan (summary + floor for the current window).
You may adjust the reserve floor by at most ±10 percentage points from the
day plan's floor for the current window, and adjust risk_level.  If you
believe the day plan itself is wrong, set request_replan to true with a
reason instead of making large changes.

Guidelines by mode:
  reliability → prioritise demand fulfilment; keep reserves ≥ 35 %
  profit      → minimise cost; reserves can go as low as 10 %
  clean       → maximise renewable usage; reserves ≥ 20 %

Raise risk_level and reserves when:
  • A storm is active or imminent (wind cut-out, line derating)
  • Renewable forecast misses exceed 30 MW
  • Battery SOC is below reserve floor
  • Evening peak is approaching with low reserves
  • Maintenance is removing generation capacity

Lower risk_level when conditions are stable and reserves are healthy.
"""


# ═══════════════════════════════════════════════════════════════════════════
# Rule-based supervisor (always available, no API key needed)
# ═══════════════════════════════════════════════════════════════════════════


def _plan_floor_at_tick(state: State) -> float:
    """Return the day plan's floor_pct for the current tick."""
    day_plan = state.get("day_plan")
    if day_plan is None:
        return 35.0
    tick = state.get("tick", 0)
    h = tick // 4
    m = (tick % 4) * 15
    t_str = f"{h:02d}:{m:02d}"
    for w in day_plan.floor_schedule:
        if w.start <= t_str < w.end:
            return w.floor_pct
    return 35.0


def _clamp_to_plan(reserve: float, plan_floor: float) -> float:
    """Clamp supervisor's reserve to plan_floor ± 10 pp."""
    return max(plan_floor - 10.0, min(plan_floor + 10.0, reserve))


def rule_supervisor(state: State) -> dict:
    mode = state.get("mode", "reliability")
    floor = state.get("reserve_floor_pct", _MODE_RESERVE.get(mode, 20.0))
    violations = state.get("violations", [])
    triggers = state.get("monitor_triggers", [])
    plan_floor = _plan_floor_at_tick(state)

    request_replan = False

    if state.get("active_storm"):
        risk = "critical"
        reserve = 10.0
        reason = (
            "Active storm — dropping reserve floor to 10 % so the battery "
            "can discharge fully to cover demand."
        )
    elif state.get("storm_alerts"):
        risk = "high"
        reserve = max(floor, 45.0)
        reason = (
            "Storm approaching — raising reserves to 45 % to prepare for "
            "potential wind cut-out and line derating."
        )
        request_replan = True
    elif any("forecast_miss" in t for t in triggers):
        risk = "medium"
        reserve = max(floor, 25.0)
        reason = "Renewable forecast miss >30 MW — increasing reserve buffer."
    else:
        risk = "low"
        reserve = plan_floor
        reason = f"Normal operations — holding reserves at {plan_floor:.0f} %."

    reserve = _clamp_to_plan(reserve, plan_floor)

    if violations:
        risk = max(risk, "medium", key=["low", "medium", "high", "critical"].index)
        reserve = max(reserve, _clamp_to_plan(30.0, plan_floor))
        v_summary = "; ".join(v.detail for v in violations[:3])
        reason += f" Validator flagged: {v_summary}"

    return {
        "risk_level": risk,
        "reserve_target_pct": reserve,
        "strategy_reason": reason,
        "request_replan": request_replan,
        "retry_count": state.get("retry_count", 0) + (1 if violations else 0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# LLM-powered supervisor (ChatGroq — Qwen 3 27B)
# ═══════════════════════════════════════════════════════════════════════════


def _build_user_message(state: State) -> str:
    lines = [
        f"Mode: {state.get('mode', 'reliability')}",
        f"Tick: {state.get('tick')} ({state.get('timestamp')})",
        f"Solar: {state.get('solar_mw', 0):.1f} MW",
        f"Wind: {state.get('wind_mw', 0):.1f} MW  (speed {state.get('wind_speed_ms', 0):.1f} m/s)",
        f"Demand: {state.get('demand_mw', 0):.1f} MW",
        f"Battery SOC: {state.get('battery_soc_pct', 0):.1f} %  "
        f"({state.get('battery_energy_mwh', 0):.1f} / "
        f"{state.get('battery_capacity_mwh', 0):.0f} MWh)",
        f"Price: ₹{state.get('price_per_kwh', 0):.2f}/kWh",
        f"Line limit: {state.get('line_limit_mw', 150)} MW",
        f"Active storm: {state.get('active_storm', False)}",
    ]

    alerts = state.get("storm_alerts", [])
    if alerts:
        for a in alerts:
            lines.append(
                f"Storm alert '{a.id}': winds {a.wind_speed_ms} m/s, "
                f"{a.storm_start}–{a.storm_end}, line derated to {a.line_limit_mw} MW"
            )

    maint = state.get("maintenance", [])
    active_maint = [m for m in maint if m.status in ("pending", "active")]
    if active_maint:
        for m in active_maint:
            lines.append(
                f"Maintenance '{m.id}': {m.asset} ({m.kind}), "
                f"{m.start}–{m.end}, status={m.status}"
            )

    violations = state.get("violations", [])
    if violations:
        lines.append("Previous validator violations:")
        for v in violations:
            lines.append(
                f"  - {v.field}: proposed={v.proposed}, "
                f"corrected={v.corrected}, limit={v.limit}"
            )

    solar_fc = state.get("solar_forecast")
    wind_fc = state.get("wind_forecast")
    demand_fc = state.get("demand_forecast")
    price_fc = state.get("price_forecast")
    if solar_fc:
        lines.append(f"Solar forecast (next 6h): {solar_fc.values[:8]}...")
    if wind_fc:
        lines.append(f"Wind forecast (next 6h): {wind_fc.values[:8]}...")
    if demand_fc:
        lines.append(f"Demand forecast (next 6h): {demand_fc.values[:8]}...")
    if price_fc:
        lines.append(f"Price forecast (next 6h): {price_fc.values[:8]}...")

    day_plan = state.get("day_plan")
    if day_plan is not None:
        plan_floor = _plan_floor_at_tick(state)
        lines.append(f"\nActive day plan: {day_plan.summary}")
        lines.append(f"Current window floor: {plan_floor:.0f}%")
        lines.append(f"Sell policy: {day_plan.sell_policy}")

    triggers = state.get("monitor_triggers", [])
    if triggers:
        lines.append(f"Monitor triggers: {triggers}")

    return "\n".join(lines)


def _parse_llm_response(content: str, state: State) -> dict | None:
    """Extract JSON from the LLM response. Returns None on parse failure."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    risk = data.get("risk_level", "").lower()
    if risk not in _VALID_RISK_LEVELS:
        return None

    try:
        reserve = float(data["reserve_target_pct"])
    except (KeyError, ValueError, TypeError):
        return None

    reserve = max(0.0, min(100.0, reserve))
    plan_floor = _plan_floor_at_tick(state)
    reserve = _clamp_to_plan(reserve, plan_floor)

    reason = str(data.get("strategy_reason", "LLM decision"))
    request_replan = bool(data.get("request_replan", False))

    violations = state.get("violations", [])
    return {
        "risk_level": risk,
        "reserve_target_pct": reserve,
        "strategy_reason": reason,
        "request_replan": request_replan,
        "retry_count": state.get("retry_count", 0) + (1 if violations else 0),
    }


def llm_supervisor(state: State) -> dict:
    """Call ChatGroq for strategic decisions. Falls back to rules on failure."""
    try:
        from langchain_groq import ChatGroq

        llm = ChatGroq(
            model="qwen/qwen3.8-27b",
            temperature=0.5,
            max_tokens=512,
        )

        messages = [
            ("system", SYSTEM_PROMPT),
            ("human", _build_user_message(state)),
        ]

        response = llm.invoke(messages)
        result = _parse_llm_response(response.content, state)
        if result is not None:
            return result

    except Exception as e:
        import sys
        print(f"[supervisor] LLM call failed, falling back to rules: {e}", file=sys.stderr)

    return rule_supervisor(state)


# ═══════════════════════════════════════════════════════════════════════════
# Dispatcher
# ═══════════════════════════════════════════════════════════════════════════


def supervisor(state: State) -> dict:
    if os.environ.get("SUPERVISOR_USE_LLM", "").lower() in ("1", "true", "yes"):
        return llm_supervisor(state)
    return rule_supervisor(state)
