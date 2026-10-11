"""Deterministic 24-hour simulator for an Indian renewable-energy utility.

Generates ground-truth arrays for solar, wind, demand, and prices across
96 ticks (15-min intervals).  Scenario events (clouds, storms, maintenance)
are layered on top.  The ``observe`` method returns a dict that maps
directly onto the LangGraph ``State`` fields filled by the data-collector
node.
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

import numpy as np
import yaml

from graph.models.state import (
    Forecast,
    MaintenanceWindow,
    StormAlert,
)

TICKS_PER_HOUR = 4
TOTAL_TICKS = 96
FORECAST_HORIZON = 96  # 24 hours at 15-min resolution


# ── helpers ───────────────────────────────────────────────────────────────

def _tick_to_hour(tick: int) -> float:
    return tick / TICKS_PER_HOUR


def _hour_to_tick(hour: float) -> int:
    return int(hour * TICKS_PER_HOUR)


def _hhmm_to_tick(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * TICKS_PER_HOUR + m // 15


def _tick_to_hhmm(tick: int) -> str:
    h = tick // TICKS_PER_HOUR
    m = (tick % TICKS_PER_HOUR) * 15
    return f"{h:02d}:{m:02d}"


# ── wind power curve ─────────────────────────────────────────────────────

def _wind_power_factor(speed: float, cut_in: float, rated: float,
                       cut_out: float) -> float:
    if speed < cut_in or speed >= cut_out:
        return 0.0
    if speed >= rated:
        return 1.0
    return ((speed - cut_in) / (rated - cut_in)) ** 3


# ═══════════════════════════════════════════════════════════════════════════

class Simulator:
    """Builds a full 24-hour truth table and serves per-tick observations."""

    def __init__(self, config: dict) -> None:
        self._cfg = config
        self._rng = np.random.default_rng(config.get("defaults", {}).get("seed", 42))

        # asset specs
        self._solar_farms = config["solar_farms"]
        self._wind_farms = config["wind_farms"]
        self._solar = config["solar"]
        self._wind = config["wind"]
        self._battery = config["battery"]
        self._factories = config["factories"]
        self._grid = config["grid"]
        self._defaults = config.get("defaults", {})

        # scenario events (may be absent)
        self._cloud_events: list[dict] = config.get("cloud_events", [])
        self._storm_events: list[dict] = config.get("storm_events", [])
        self._maint_windows: list[dict] = config.get("maintenance_windows", [])

        # build truth arrays (96 ticks each)
        self._solar_truth = self._build_solar()        # MW per tick
        self._wind_speed_truth = self._build_wind_speed()  # m/s per tick
        self._wind_truth = self._build_wind_power()    # MW per tick (uses speed truth)
        self._demand_truth = self._build_demand()      # MW per tick
        self._price_truth = self._build_prices()       # ₹/kWh per tick

        # apply scenario events on top of truth
        self._apply_cloud_events()
        self._apply_storm_events()
        self._apply_maintenance()

        # build forecasts (refreshed each hour, stale between refreshes)
        self._solar_fc = self._build_forecast(self._solar_truth,
                                              self._solar["forecast_error_pct"])
        self._wind_fc = self._build_forecast(self._wind_truth,
                                              self._wind["forecast_speed_error_ms"]
                                              / self._wind["base_speed_ms"])
        self._demand_fc = self._build_forecast(self._demand_truth, 0.05)
        self._price_fc = self._build_forecast(self._price_truth, 0.10)

        # battery state (mutable — updated each observe call)
        cap = self._battery.get("capacity_mwh", 0.0)
        init_pct = self._battery.get("soc_init_pct", 0.0)
        self._battery_energy = cap * init_pct / 100.0 if cap > 0 else 0.0

    # ── solar generation ──────────────────────────────────────────────────

    def _build_solar(self) -> np.ndarray:
        sunrise = self._solar["sunrise_hour"]
        sunset = self._solar["sunset_hour"]
        peak_cf = self._solar["peak_capacity_factor"]
        total_cap = self._solar["total_capacity_mw"]

        out = np.zeros(TOTAL_TICKS)
        for t in range(TOTAL_TICKS):
            h = _tick_to_hour(t)
            if sunrise <= h <= sunset:
                mid = (sunrise + sunset) / 2
                width = (sunset - sunrise) / 2
                cf = peak_cf * math.exp(-0.5 * ((h - mid) / (width / 2.5)) ** 2)
                out[t] = total_cap * cf
        return out

    # ── wind speed + power ────────────────────────────────────────────────

    def _build_wind_speed(self) -> np.ndarray:
        base = self._wind["base_speed_ms"]
        evening = self._wind["evening_speed_ms"]
        speeds = np.zeros(TOTAL_TICKS)
        for t in range(TOTAL_TICKS):
            h = _tick_to_hour(t)
            # diurnal pattern: lower midday, higher evening
            diurnal = base + (evening - base) * (0.5 + 0.5 * math.sin(
                2 * math.pi * (h - 6) / 24))
            noise = self._rng.normal(0, 0.5)
            speeds[t] = max(0.0, diurnal + noise)
        return speeds

    def _build_wind_power(self) -> np.ndarray:
        cut_in = self._wind["cut_in_ms"]
        rated = self._wind["rated_ms"]
        cut_out = self._wind["cut_out_ms"]
        total_cap = self._wind["total_capacity_mw"]

        out = np.zeros(TOTAL_TICKS)
        for t in range(TOTAL_TICKS):
            pf = _wind_power_factor(self._wind_speed_truth[t],
                                    cut_in, rated, cut_out)
            out[t] = total_cap * pf
        return out

    # ── demand ────────────────────────────────────────────────────────────

    def _build_demand(self) -> np.ndarray:
        out = np.zeros(TOTAL_TICKS)
        for t in range(TOTAL_TICKS):
            h = _tick_to_hour(t)
            total = 0.0
            for f in self._factories:
                total += f["base_mw"]
                if f["start_hour"] <= h < f["end_hour"]:
                    total += f["day_mw"]
            noise = self._rng.normal(0, total * 0.02)
            out[t] = max(0.0, total + noise)
        return out

    # ── prices ────────────────────────────────────────────────────────────

    def _build_prices(self) -> np.ndarray:
        out = np.zeros(TOTAL_TICKS)
        for t in range(TOTAL_TICKS):
            h = _tick_to_hour(t)
            if h < 6:
                base = 3.0
            elif h < 11:
                base = 3.0 - 0.6 * (h - 6) / 5  # drift down toward solar noon
            elif h < 15:
                base = 2.4                         # solar surplus
            elif h < 19:
                base = 2.4 + 7.1 * ((h - 15) / 4) ** 2  # ramp to evening peak
            elif h < 20:
                base = 9.5                         # evening peak
            elif h <= 24:
                base = 9.5 - 5.5 * (h - 20) / 4  # settle back
            else:
                base = 3.0
            noise = self._rng.normal(0, base * 0.10)
            out[t] = max(0.01, min(base + noise, self._grid["price_cap_per_kwh"]))
        return out

    # ── scenario event overlays ───────────────────────────────────────────

    def _apply_cloud_events(self) -> None:
        farm_caps = {f["id"]: f["capacity_mw"] for f in self._solar_farms}
        total_cap = self._solar["total_capacity_mw"]
        if total_cap <= 0:
            return
        for ev in self._cloud_events:
            t0 = _hhmm_to_tick(ev["start"])
            t1 = _hhmm_to_tick(ev["end"])
            affected_cap = sum(farm_caps.get(fid, 0) for fid in ev["farms"])
            reduction = affected_cap * (1 - ev["output_factor"]) / total_cap
            for t in range(t0, min(t1, TOTAL_TICKS)):
                self._solar_truth[t] *= (1 - reduction)

    def _apply_storm_events(self) -> None:
        cut_out = self._wind["cut_out_ms"]
        rated = self._wind["rated_ms"]
        cut_in = self._wind["cut_in_ms"]
        total_cap = self._wind["total_capacity_mw"]

        for ev in self._storm_events:
            t0 = _hhmm_to_tick(ev["storm_start"])
            t1 = _hhmm_to_tick(ev["storm_end"])
            for t in range(t0, min(t1, TOTAL_TICKS)):
                self._wind_speed_truth[t] = ev["wind_speed_ms"]
                pf = _wind_power_factor(ev["wind_speed_ms"],
                                        cut_in, rated, cut_out)
                self._wind_truth[t] = total_cap * pf

    def _apply_maintenance(self) -> None:
        wind_caps = {f["id"]: f["capacity_mw"] for f in self._wind_farms}
        solar_caps = {f["id"]: f["capacity_mw"] for f in self._solar_farms}
        wind_total = self._wind["total_capacity_mw"]
        solar_total = self._solar["total_capacity_mw"]

        for mw in self._maint_windows:
            t0 = _hhmm_to_tick(mw["start"])
            t1 = _hhmm_to_tick(mw["end"])
            asset = mw["asset"]

            if asset in wind_caps and wind_total > 0:
                factor = 1 - wind_caps[asset] / wind_total
                for t in range(t0, min(t1, TOTAL_TICKS)):
                    self._wind_truth[t] *= factor

            elif asset in solar_caps and solar_total > 0:
                factor = 1 - solar_caps[asset] / solar_total
                for t in range(t0, min(t1, TOTAL_TICKS)):
                    self._solar_truth[t] *= factor

    # ── forecasts ─────────────────────────────────────────────────────────

    def _build_forecast(self, truth: np.ndarray,
                        base_error: float) -> list[list[float]]:
        """One forecast per tick. Refreshes every hour; stale in between."""
        forecasts: list[list[float]] = []
        cached: list[float] | None = None
        for t in range(TOTAL_TICKS):
            if t % TICKS_PER_HOUR == 0 or cached is None:
                vals: list[float] = []
                for k in range(FORECAST_HORIZON):
                    ft = t + k
                    if ft >= TOTAL_TICKS:
                        vals.append(0.0)
                    else:
                        lead_factor = 1 + k / FORECAST_HORIZON
                        noise = self._rng.normal(0, base_error * lead_factor)
                        vals.append(max(0.0, float(truth[ft] * (1 + noise))))
                cached = vals
            forecasts.append(list(cached))
        return forecasts

    # ── alerts & maintenance state ────────────────────────────────────────

    def _get_storm_alerts(self, tick: int) -> list[StormAlert]:
        alerts: list[StormAlert] = []
        for ev in self._storm_events:
            alert_tick = _hhmm_to_tick(ev["alert_time"])
            storm_end_tick = _hhmm_to_tick(ev["storm_end"])
            if alert_tick <= tick < storm_end_tick:
                alerts.append(StormAlert(
                    id=ev["id"],
                    alert_time=ev["alert_time"],
                    storm_start=ev["storm_start"],
                    storm_end=ev["storm_end"],
                    wind_speed_ms=ev["wind_speed_ms"],
                    line_limit_mw=ev["line_limit_mw"],
                    notice=ev.get("notice", ""),
                ))
        return alerts

    def _is_active_storm(self, tick: int) -> bool:
        for ev in self._storm_events:
            t0 = _hhmm_to_tick(ev["storm_start"])
            t1 = _hhmm_to_tick(ev["storm_end"])
            if t0 <= tick < t1:
                return True
        return False

    def _get_maintenance(self, tick: int) -> list[MaintenanceWindow]:
        windows: list[MaintenanceWindow] = []
        for mw in self._maint_windows:
            t0 = _hhmm_to_tick(mw["start"])
            t1 = _hhmm_to_tick(mw["end"])
            if tick < t0:
                status = "pending"
            elif tick < t1:
                status = "active"
            else:
                status = "completed"
            windows.append(MaintenanceWindow(
                id=mw["id"],
                asset=mw["asset"],
                kind=mw["kind"],
                start=mw["start"],
                end=mw["end"],
                status=status,
            ))
        return windows

    def _get_line_limit(self, tick: int) -> float:
        limit = float(self._grid["line_limit_mw"])
        for ev in self._storm_events:
            t0 = _hhmm_to_tick(ev["storm_start"])
            t1 = _hhmm_to_tick(ev["storm_end"])
            if t0 <= tick < t1:
                limit = min(limit, ev["line_limit_mw"])
        return limit

    # ── main observation API ──────────────────────────────────────────────

    def observe(self, tick: int) -> dict[str, Any]:
        """Return a dict of State fields for the given tick."""
        if not 0 <= tick < TOTAL_TICKS:
            raise ValueError(f"tick must be 0–95, got {tick}")

        solar = float(self._solar_truth[tick])
        wind = float(self._wind_truth[tick])
        wind_speed = float(self._wind_speed_truth[tick])
        demand = float(self._demand_truth[tick])
        price = float(self._price_truth[tick])

        bat = self._battery
        cap = bat.get("capacity_mwh", 0.0)
        soc_pct = (self._battery_energy / cap * 100.0) if cap > 0 else 0.0

        return {
            # time
            "tick": tick,
            "timestamp": _tick_to_hhmm(tick),

            # solar
            "solar_mw": round(solar, 2),
            "solar_forecast": Forecast(
                values=[round(v, 2) for v in self._solar_fc[tick]]),

            # wind
            "wind_mw": round(wind, 2),
            "wind_forecast": Forecast(
                values=[round(v, 2) for v in self._wind_fc[tick]]),
            "wind_speed_ms": round(wind_speed, 2),

            # renewables aggregate
            "renewables_mw": round(solar + wind, 2),

            # demand
            "demand_mw": round(demand, 2),
            "demand_forecast": Forecast(
                values=[round(v, 2) for v in self._demand_fc[tick]]),

            # battery
            "battery_soc_pct": round(soc_pct, 2),
            "battery_energy_mwh": round(self._battery_energy, 2),
            "battery_capacity_mwh": float(cap),
            "battery_max_charge_mw": float(bat.get("max_charge_mw", 0.0)),
            "battery_max_discharge_mw": float(bat.get("max_discharge_mw", 0.0)),
            "battery_min_energy_mwh": cap * bat.get("soc_min_pct", 0.0) / 100.0 if cap > 0 else 0.0,
            "battery_max_energy_mwh": cap * bat.get("soc_max_pct", 100.0) / 100.0 if cap > 0 else 0.0,

            # market
            "price_per_kwh": round(price, 4),
            "price_forecast": Forecast(
                values=[round(v, 4) for v in self._price_fc[tick]]),

            # grid
            "line_limit_mw": self._get_line_limit(tick),
            "line_limit_nominal_mw": float(self._grid["line_limit_mw"]),

            # alerts & maintenance
            "storm_alerts": self._get_storm_alerts(tick),
            "active_storm": self._is_active_storm(tick),
            "maintenance": self._get_maintenance(tick),
        }

    def update_battery(self, delta_mwh: float) -> None:
        """Apply a charge (+) or discharge (−) delta to battery energy."""
        cap = self._battery.get("capacity_mwh", 0.0)
        if cap <= 0:
            return
        floor = cap * self._battery.get("soc_min_pct", 0.0) / 100.0
        ceil = cap * self._battery.get("soc_max_pct", 100.0) / 100.0
        self._battery_energy = max(floor, min(ceil,
                                              self._battery_energy + delta_mwh))


# ── convenience loader ────────────────────────────────────────────────────

def load_config(*yaml_paths: str) -> dict:
    """Merge multiple YAML files into one config dict (later files overlay)."""
    merged: dict = {}
    for path in yaml_paths:
        with open(path) as f:
            data = yaml.safe_load(f)
            if data:
                merged.update(data)
    return merged
