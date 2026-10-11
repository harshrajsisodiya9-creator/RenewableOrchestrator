"""LangGraph node: day planner — sets strategic plan via LLM (rarely called)."""

from __future__ import annotations

import json
import logging
import os
import sys

from graph.models.state import DayPlan, FloorWindow, State

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("planner")

DEFAULT_PLAN = DayPlan()

PLANNER_SYSTEM_PROMPT = """\
You are the day planner for a renewable microgrid with solar, wind, a battery, \
and a grid connection. You receive a 24-hour hourly summary of forecast price \
(₹/kWh), demand, solar and wind (MW), the battery state of charge, precomputed \
peak and cheapest windows, the evening energy need, and any weather alerts.

Your job is strategy, not dispatch. A separate optimizer computes exact MW every \
15 minutes using your plan. Do not output MW values or arithmetic; output only \
the fields in the schema.

Decide:
1. floor_schedule: the minimum battery state of charge (%) for each time window \
of the day. Raise the floor before periods where reliability matters (demand ramps, \
evening peak, storm windows). Lower it when renewables will refill the battery \
(midday solar). Keep 35% as the default.
2. sell_policy: "no_sell" if the battery should keep all surplus (storm coming, \
or battery below what the evening needs), "only_above_terminal" normally, "free" \
only if the battery is near full and surplus is large.
3. risk_level, based on forecast uncertainty and alerts.
4. storm_actions: for each alert, concrete expectations in plain words \
(e.g. "wind turbines may cut out 18:00-22:00; hold 70% from 15:00"). Empty list \
if no alerts.
5. summary: 2-3 plain sentences an operator can read in 10 seconds.

Prefer reliability over profit when alerts are present. Never invent data that \
is not in the input.

Respond with ONLY a JSON object (no markdown, no commentary) with exactly these keys:
  summary: str
  risk_level: "low" | "medium" | "high"
  floor_schedule: list of {start: "HH:MM", end: "HH:MM", floor_pct: float}
  sell_policy: "free" | "only_above_terminal" | "no_sell"
  storm_actions: list of str
  reasoning: str
"""


def _build_planner_message(state: State) -> str:
    features = state.get("features", {})
    lines = [
        "=== 24-HOUR FORECAST SUMMARY ===",
    ]

    hourly = features.get("hourly_summary", [])
    if hourly:
        lines.append(
            "Hour | Price ₹/kWh | Demand MW | Solar MW | Wind MW | Net MW"
        )
        for h in hourly:
            lines.append(
                f"  {h['hour']:2d}  |   {h['avg_price']:6.2f}   |  {h['avg_demand_mw']:6.1f}  | "
                f"{h['avg_solar_mw']:6.1f}  | {h['avg_wind_mw']:5.1f}  | {h['net_mw']:+7.1f}"
            )

    lines.append("")
    lines.append("=== PRECOMPUTED ANALYSIS ===")
    lines.append(f"Peak window (ticks): {features.get('peak_window', 'N/A')}")
    lines.append(
        f"Peak avg price: ₹{features.get('peak_avg_price', 0):.2f}/kWh"
    )
    lines.append(f"Evening energy need: {features.get('e_need_mwh', 0):.1f} MWh")
    lines.append(f"Cheapest window (hours): {features.get('cheapest_window', 'N/A')}")
    lines.append(
        f"Midday surplus: {features.get('midday_surplus_mwh', 0):.1f} MWh"
    )

    lines.append("")
    lines.append("=== BATTERY STATE ===")
    lines.append(f"SoC: {features.get('soc_pct', 0):.1f}%")
    lines.append(f"Energy: {features.get('soc_mwh', 0):.1f} MWh")

    alerts = features.get("alerts", [])
    if alerts:
        lines.append("")
        lines.append("=== WEATHER ALERTS ===")
        for a in alerts:
            lines.append(f"  - {a}")

    return "\n".join(lines)


def _clamp_plan(raw: dict) -> DayPlan:
    """Validate and clamp a raw JSON dict into a DayPlan."""
    summary = str(raw.get("summary", DEFAULT_PLAN.summary))
    risk = str(raw.get("risk_level", "medium")).lower()
    if risk not in ("low", "medium", "high"):
        risk = "medium"

    sell_policy = str(raw.get("sell_policy", "only_above_terminal"))
    if sell_policy not in ("free", "only_above_terminal", "no_sell"):
        sell_policy = "only_above_terminal"

    storm_actions = raw.get("storm_actions", [])
    if not isinstance(storm_actions, list):
        storm_actions = []
    storm_actions = [str(a) for a in storm_actions]

    reasoning = str(raw.get("reasoning", ""))

    raw_schedule = raw.get("floor_schedule", [])
    if not isinstance(raw_schedule, list):
        raw_schedule = []

    windows: list[FloorWindow] = []
    for w in raw_schedule:
        if not isinstance(w, dict):
            continue
        start = str(w.get("start", "00:00"))
        end = str(w.get("end", "24:00"))
        pct = float(w.get("floor_pct", 35.0))
        pct = max(20.0, min(80.0, pct))
        windows.append(FloorWindow(start=start, end=end, floor_pct=pct))

    windows.sort(key=lambda w: w.start)

    if not windows:
        windows = [FloorWindow("00:00", "24:00", 35.0)]
    else:
        filled: list[FloorWindow] = []
        cursor = "00:00"
        for w in windows:
            if w.start > cursor:
                filled.append(FloorWindow(cursor, w.start, 35.0))
            if w.start < cursor:
                w = FloorWindow(cursor, w.end, max(w.floor_pct, filled[-1].floor_pct) if filled else w.floor_pct)
            filled.append(w)
            cursor = w.end
        if cursor < "24:00":
            filled.append(FloorWindow(cursor, "24:00", 35.0))
        windows = filled

    return DayPlan(
        summary=summary,
        risk_level=risk,
        floor_schedule=windows,
        sell_policy=sell_policy,
        storm_actions=storm_actions,
        reasoning=reasoning,
    )


def _call_llm(state: State) -> DayPlan | None:
    """Call ChatGroq for day planning. Returns None on failure."""
    try:
        from langchain_groq import ChatGroq

        llm = ChatGroq(
            model="qwen/qwen3.8-27b",
            temperature=0.3,
            max_tokens=1024,
            timeout=10,
        )

        messages = [
            ("system", PLANNER_SYSTEM_PROMPT),
            ("human", _build_planner_message(state)),
        ]

        response = llm.invoke(messages)
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        raw = json.loads(text)
        plan = _clamp_plan(raw)
        log.info("Planner LLM returned plan: %s", plan.summary)
        return plan

    except Exception as e:
        print(
            f"[planner] LLM call failed, using fallback: {e}",
            file=sys.stderr,
        )
        return None


def planner(state: State) -> dict:
    """Day planner node — produces a DayPlan for the optimizer and supervisor."""
    tick = state.get("tick", 0)
    prev_plan: DayPlan | None = state.get("day_plan")
    llm_fallback = False

    if os.environ.get("SUPERVISOR_USE_LLM", "").lower() in ("1", "true", "yes"):
        result = _call_llm(state)
        if result is not None:
            plan = result
        else:
            llm_fallback = True
            plan = prev_plan if prev_plan is not None else DEFAULT_PLAN
    else:
        plan = _rule_planner(state)

    log.info(
        "tick=%d  PLAN  risk=%s  sell_policy=%s  floors=%s  summary=%s",
        tick,
        plan.risk_level,
        plan.sell_policy,
        [(w.start, w.end, w.floor_pct) for w in plan.floor_schedule],
        plan.summary,
    )

    return {
        "day_plan": plan,
        "planner_called": True,
        "llm_fallback_used": llm_fallback,
    }


def _rule_planner(state: State) -> DayPlan:
    """Rule-based planner fallback — no LLM needed."""
    features = state.get("features", {})
    alerts = features.get("alerts", [])
    soc_pct = features.get("soc_pct", 50.0)
    e_need = features.get("e_need_mwh", 0.0)

    if alerts:
        risk = "high"
        sell_policy = "no_sell"
        storm_actions = [f"Alert active: {a}" for a in alerts]
        floor_schedule = [
            FloorWindow("00:00", "15:00", 35.0),
            FloorWindow("15:00", "22:00", 40.0),
            FloorWindow("22:00", "24:00", 35.0),
        ]
        summary = "Storm alerts present — raising reserves and blocking sales."
    elif e_need > 100:
        risk = "medium"
        sell_policy = "only_above_terminal"
        storm_actions = []
        floor_schedule = [
            FloorWindow("00:00", "06:00", 35.0),
            FloorWindow("06:00", "10:00", 30.0),
            FloorWindow("10:00", "15:00", 25.0),
            FloorWindow("15:00", "20:00", 50.0),
            FloorWindow("20:00", "24:00", 35.0),
        ]
        summary = f"High evening need ({e_need:.0f} MWh) — building reserves from midday."
    else:
        risk = "low"
        sell_policy = "only_above_terminal"
        storm_actions = []
        floor_schedule = [FloorWindow("00:00", "24:00", 35.0)]
        summary = "Normal day — standard reserves."

    return DayPlan(
        summary=summary,
        risk_level=risk,
        floor_schedule=floor_schedule,
        sell_policy=sell_policy,
        storm_actions=storm_actions,
        reasoning="Rule-based planner",
    )
