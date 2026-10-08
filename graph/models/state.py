from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

# ---------------------------------------------------------------------------
# Helper dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Forecast:
    """6-hour-ahead forecast: one float per 15-min interval (24 values).

    The unit depends on which state field holds the forecast:
      solar_forecast  → predicted solar generation (MW per interval)
      wind_forecast   → predicted wind generation (MW per interval)
      demand_forecast → predicted factory demand (MW per interval)
      price_forecast  → predicted electricity price (₹/kWh per interval)
    """

    values: list[float] = field(default_factory=list)


@dataclass
class StormAlert:
    """Weather bureau storm warning pushed to the grid operator."""

    id: str
    alert_time: str  # ISO-8601 when the alert was issued
    storm_start: str  # ISO-8601 expected storm arrival
    storm_end: str  # ISO-8601 expected storm departure
    wind_speed_ms: float  # peak sustained wind (m/s)
    line_limit_mw: float  # derated transmission limit during storm
    notice: str  # human-readable summary


@dataclass
class MaintenanceWindow:
    """Scheduled or forced outage for a generation / storage asset."""

    id: str
    asset: str  # e.g. "solar_farm_1", "battery_B2"
    kind: str  # "scheduled" | "forced"
    start: str  # ISO-8601
    end: str  # ISO-8601
    status: str  # "pending" | "active" | "completed"


@dataclass
class Action:
    """Dispatch decision produced by the optimizer for one tick."""

    charge: float = 0.0  # MW into the battery
    discharge: float = 0.0  # MW out of the battery
    buy: float = 0.0  # MW purchased from the grid
    sell: float = 0.0  # MW sold to the grid
    curtail: float = 0.0  # MW of renewable generation curtailed
    unmet: float = 0.0  # MW of demand left unserved


@dataclass
class Violation:
    """Structured feedback from the validator back to the LLM supervisor."""

    field: str  # which Action field was violated
    proposed: float  # value the optimizer proposed
    corrected: float  # value the validator replaced it with
    limit: float  # hard constraint that was breached
    detail: str  # human-readable explanation


# ---------------------------------------------------------------------------
# LangGraph State  (total=False → every field is optional)
# ---------------------------------------------------------------------------


class State(TypedDict, total=False):
    # ── Time ──────────────────────────────────────────────────────────────
    tick: int  # 0-95, each tick = 15 min
    timestamp: str  # "HH:MM" for display / logs

    # ── Solar ─────────────────────────────────────────────────────────────
    solar_mw: float  # current solar output (MW)
    solar_forecast: Forecast  # 6 h ahead (filled by data node)

    # ── Wind ──────────────────────────────────────────────────────────────
    wind_mw: float  # current wind output (MW)
    wind_forecast: Forecast  # 6 h ahead (filled by data node)
    wind_speed_ms: float  # current wind speed (m/s)

    # ── Renewables (aggregate) ────────────────────────────────────────────
    renewables_mw: float  # solar_mw + wind_mw

    # ── Demand ────────────────────────────────────────────────────────────
    demand_mw: float  # current load (MW)
    demand_forecast: Forecast  # 6 h ahead (filled by data node)

    # ── Battery (combined B1 + B2) ────────────────────────────────────────
    battery_soc_pct: float  # state-of-charge 0-100 %
    battery_energy_mwh: float  # current stored energy (MWh)
    battery_capacity_mwh: float  # nameplate capacity (MWh)
    battery_max_charge_mw: float  # max charging rate (MW)
    battery_max_discharge_mw: float  # max discharging rate (MW)
    battery_min_energy_mwh: float  # hard floor (MWh)
    battery_max_energy_mwh: float  # hard ceiling (MWh)

    # ── Market ────────────────────────────────────────────────────────────
    price_per_kwh: float  # current spot price (₹/kWh)
    price_forecast: Forecast  # 6 h ahead (filled by data node)

    # ── Grid ──────────────────────────────────────────────────────────────
    line_limit_mw: float  # transmission capacity (MW)

    # ── Alerts & maintenance ──────────────────────────────────────────────
    storm_alerts: list[StormAlert]  # active storm warnings
    active_storm: bool  # True while a storm window is open
    maintenance: list[MaintenanceWindow]  # scheduled / forced outages

    # ── Config (set once at startup) ──────────────────────────────────────
    mode: str  # "reliability" | "profit" | "clean"
    reserve_floor_pct: float  # min battery reserve (%)
    carbon_price_per_tonne: float  # shadow carbon price (₹/t)
    curtail_penalty_per_kwh: float  # penalty for curtailment (₹/kWh)

    # ── Monitor output ────────────────────────────────────────────────────
    should_call_supervisor: bool  # True → route to LLM supervisor
    monitor_triggers: list[str]  # reasons the monitor flagged this tick

    # ── Supervisor (LLM) output ───────────────────────────────────────────
    risk_level: str  # "low" | "medium" | "high" | "critical"
    reserve_target_pct: float  # dynamic reserve target from LLM (%)
    strategy_reason: str  # LLM explanation for its decision

    # ── Optimizer output ──────────────────────────────────────────────────
    plan: Action  # dispatch plan for this tick
    plan_status: str  # "optimal" | "fallback" | "error"

    # ── Validator output ──────────────────────────────────────────────────
    validated_action: Action  # plan after constraint enforcement
    validation_passed: bool  # True if plan needed no corrections
    violations: list[Violation]  # what was corrected and why
    retry_count: int  # times optimizer was re-invoked

    # ── Logger output ─────────────────────────────────────────────────────
    tick_log: list[dict]  # accumulated per-tick records
