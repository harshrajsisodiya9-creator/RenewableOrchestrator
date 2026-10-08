"""LangGraph node: strategic brain — sets risk level and reserve targets."""

from __future__ import annotations

import json
import os

from graph.models.state import State

_MODE_RESERVE: dict[str, float] = {
    "reliability": 35.0,
    "profit": 10.0,
    "clean": 20.0,
}

_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}

SYSTEM_PROMPT = """\
You are the strategic supervisor of renewable-energy microgrid.

Your job: assess the current grid situation and set the operating strategy
for the next interval.  You MUST respond with ONLY a JSON object no
markdown, no commentary with exactly these keys:

  risk_level one of: low, medium, high, critical
  reserve_target_pct:float 0 to 100, battery reserve floor (% of capacity)
  strategy_reason: one sentence explaining your decision

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


def rule_supervisor(state: State) -> dict:
    mode = state.get("mode", "reliability")
    floor = state.get("reserve_floor_pct", _MODE_RESERVE.get(mode, 20.0))
    violations = state.get("violations", [])
    triggers = state.get("monitor_triggers", [])

    if state.get("active_storm"):
        # storm is HERE — battery is the only flexible resource, let it drain
        risk = "critical"
        reserve = 10.0
        reason = (
            "Active storm — dropping reserve floor to 10 % so the battery "
            "can discharge fully to cover demand."
        )
    elif state.get("storm_alerts"):
        # storm is COMING — build reserves before it hits
        risk = "high"
        reserve = max(floor, 45.0)
        reason = (
            "Storm approaching — raising reserves to 45 % to prepare for "
            "potential wind cut-out and line derating."
        )
    elif any("forecast_miss" in t for t in triggers):
        risk = "medium"
        reserve = max(floor, 25.0)
        reason = "Renewable forecast miss >30 MW — increasing reserve buffer."
    else:
        risk = "low"
        reserve = floor
        reason = f"Normal operations — holding reserves at {floor:.0f} %."

    if violations:
        risk = max(risk, "medium", key=["low", "medium", "high", "critical"].index)
        reserve = max(reserve, 30.0)
        v_summary = "; ".join(v.detail for v in violations[:3])
        reason += f" Validator flagged: {v_summary}"

    return {
        "risk_level": risk,
        "reserve_target_pct": reserve,
        "strategy_reason": reason,
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

    triggers = state.get("monitor_triggers", [])
    if triggers:
        lines.append(f"Monitor triggers: {triggers}")

    return "\n".join(lines)


def _parse_llm_response(content: str, state: State) -> dict | None:
    """Extract JSON from the LLM response. Returns None on parse failure."""
    text = content.strip()
    # strip markdown fences if present
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
    reason = str(data.get("strategy_reason", "LLM decision"))

    violations = state.get("violations", [])
    return {
        "risk_level": risk,
        "reserve_target_pct": reserve,
        "strategy_reason": reason,
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
