from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


# ── request schemas ──────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str


class SolarFarmCreate(BaseModel):
    id: str
    power_output_mw: float
    project_name: str

    @field_validator("id")
    @classmethod
    def validate_solar_id(cls, v: str) -> str:
        if not re.fullmatch(r"S\d+", v):
            raise ValueError("Solar farm ID must match pattern S1, S2, ...")
        return v


class WindFarmCreate(BaseModel):
    id: str
    power_output_mw: float
    project_name: str

    @field_validator("id")
    @classmethod
    def validate_wind_id(cls, v: str) -> str:
        if not re.fullmatch(r"W\d+", v):
            raise ValueError("Wind farm ID must match pattern W1, W2, ...")
        return v


class BatteryCreate(BaseModel):
    id: str
    capacity_mwh: float
    max_rate_mw: float
    min_soc_pct: float = 10.0
    max_soc_pct: float = 95.0
    initial_soc_pct: float = 50.0
    project_name: str

    @field_validator("id")
    @classmethod
    def validate_battery_id(cls, v: str) -> str:
        if not re.fullmatch(r"B\d+", v):
            raise ValueError("Battery ID must match pattern B1, B2, ...")
        return v


class ConsumerCreate(BaseModel):
    id: str
    day_load_mw: float
    night_load_mw: float
    shift_start: str = "06:00"
    shift_end: str = "22:00"
    project_name: str

    @field_validator("id")
    @classmethod
    def validate_consumer_id(cls, v: str) -> str:
        if not re.fullmatch(r"C\d+", v):
            raise ValueError("Consumer ID must match pattern C1, C2, ...")
        return v

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("Must be HH:MM format")
        h, m = map(int, v.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid time")
        return v


class FactoryCreate(BaseModel):
    id: str
    priority: str
    base_mw: float
    day_mw: float
    start_hour: float
    end_hour: float
    project_name: str


class GridCreate(BaseModel):
    line_limit_mw: float
    buy_premium_per_kwh: float
    price_cap_per_kwh: float
    emission_tco2_per_mwh: float
    project_name: str


# ── full project create (single-request) ────────────────────────────────


class SolarFarmInput(BaseModel):
    id: str
    power_output_mw: float

    @field_validator("id")
    @classmethod
    def validate_solar_id(cls, v: str) -> str:
        if not re.fullmatch(r"S\d+", v):
            raise ValueError("Solar farm ID must match pattern S1, S2, ...")
        return v

    @field_validator("power_output_mw")
    @classmethod
    def positive_mw(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Power output must be > 0")
        return v


class WindFarmInput(BaseModel):
    id: str
    power_output_mw: float

    @field_validator("id")
    @classmethod
    def validate_wind_id(cls, v: str) -> str:
        if not re.fullmatch(r"W\d+", v):
            raise ValueError("Wind farm ID must match pattern W1, W2, ...")
        return v

    @field_validator("power_output_mw")
    @classmethod
    def positive_mw(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Power output must be > 0")
        return v


class BatteryInput(BaseModel):
    id: str
    capacity_mwh: float
    max_rate_mw: float
    min_soc_pct: float = 10.0
    max_soc_pct: float = 95.0
    initial_soc_pct: float = 50.0

    @field_validator("id")
    @classmethod
    def validate_battery_id(cls, v: str) -> str:
        if not re.fullmatch(r"B\d+", v):
            raise ValueError("Battery ID must match pattern B1, B2, ...")
        return v

    @field_validator("capacity_mwh", "max_rate_mw")
    @classmethod
    def positive_values(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Value must be > 0")
        return v

    @model_validator(mode="after")
    def soc_range(self):
        if not (0 <= self.min_soc_pct <= 100):
            raise ValueError("min SOC must be 0–100")
        if not (0 <= self.max_soc_pct <= 100):
            raise ValueError("max SOC must be 0–100")
        if not (0 <= self.initial_soc_pct <= 100):
            raise ValueError("initial SOC must be 0–100")
        if self.min_soc_pct >= self.initial_soc_pct:
            raise ValueError("min SOC must be < initial SOC")
        if self.initial_soc_pct >= self.max_soc_pct:
            raise ValueError("initial SOC must be < max SOC")
        return self


class ConsumerInput(BaseModel):
    id: str
    day_load_mw: float
    night_load_mw: float
    shift_start: str = "06:00"
    shift_end: str = "22:00"

    @field_validator("id")
    @classmethod
    def validate_consumer_id(cls, v: str) -> str:
        if not re.fullmatch(r"C\d+", v):
            raise ValueError("Consumer ID must match pattern C1, C2, ...")
        return v

    @field_validator("day_load_mw", "night_load_mw")
    @classmethod
    def positive_load(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Load must be > 0")
        return v

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("Must be HH:MM format")
        h, m = map(int, v.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid time")
        return v


class GridInput(BaseModel):
    line_limit_mw: float
    buy_premium_per_kwh: float = 0.0
    price_cap_per_kwh: float = 0.0
    emission_tco2_per_mwh: float = 0.0

    @field_validator("line_limit_mw")
    @classmethod
    def non_negative_limit(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Line limit must be >= 0 (0 = islanded)")
        return v


class ProjectFullCreate(BaseModel):
    name: str
    solar_farms: list[SolarFarmInput] = []
    wind_farms: list[WindFarmInput] = []
    batteries: list[BatteryInput] = []
    consumers: list[ConsumerInput] = []
    grid: GridInput

    @field_validator("name")
    @classmethod
    def name_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Project name is required")
        return v.strip()

    @model_validator(mode="after")
    def cross_field_rules(self):
        if not self.consumers:
            raise ValueError("At least one consumer is required")

        has_farms = bool(self.solar_farms or self.wind_farms)
        has_batteries = bool(self.batteries)
        has_grid_import = self.grid.line_limit_mw > 0
        if not (has_farms or has_batteries or has_grid_import):
            raise ValueError(
                "At least one supply path is required: "
                "a solar farm, wind farm, battery, or line limit > 0"
            )

        all_ids = (
            [s.id for s in self.solar_farms]
            + [w.id for w in self.wind_farms]
            + [b.id for b in self.batteries]
            + [c.id for c in self.consumers]
        )
        if len(all_ids) != len(set(all_ids)):
            seen: set[str] = set()
            dupes: set[str] = set()
            for i in all_ids:
                if i in seen:
                    dupes.add(i)
                seen.add(i)
            raise ValueError(f"Duplicate IDs: {', '.join(sorted(dupes))}")

        total_supply = (
            sum(s.power_output_mw for s in self.solar_farms)
            + sum(w.power_output_mw for w in self.wind_farms)
            + sum(b.max_rate_mw for b in self.batteries)
            + self.grid.line_limit_mw
        )
        peak_demand = 0.0
        for quarter in range(96):
            h = quarter * 0.25
            load = 0.0
            for c in self.consumers:
                sh, sm = map(int, c.shift_start.split(":"))
                eh, em = map(int, c.shift_end.split(":"))
                load += c.day_load_mw if (sh + sm / 60) <= h < (eh + em / 60) else c.night_load_mw
            peak_demand = max(peak_demand, load)
        if peak_demand > total_supply:
            raise ValueError(
                "Peak concurrent demand ({:.1f} MW) exceeds "
                "total supply capacity ({:.1f} MW)".format(peak_demand, total_supply)
            )

        return self


class InjectRequest(BaseModel):
    asset_type: Literal["solar", "wind", "battery", "grid"]
    asset_id: str
    action: Literal["trip", "restore"]
    duration_ticks: int | None = None
    project_name: str


class InjectResponse(BaseModel):
    asset_type: str
    asset_id: str
    status: str
    tripped_at: int | None
    restore_at: int | None
    message: str


# ── response schemas ─────────────────────────────────────────────────────


class ProjectResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class SolarFarmResponse(BaseModel):
    id: str
    power_output_mw: float
    project_name: str


class WindFarmResponse(BaseModel):
    id: str
    power_output_mw: float
    project_name: str


class BatteryResponse(BaseModel):
    id: str
    capacity_mwh: float
    max_rate_mw: float
    min_soc_pct: float
    max_soc_pct: float
    initial_soc_pct: float
    project_name: str


class ConsumerResponse(BaseModel):
    id: str
    day_load_mw: float
    night_load_mw: float
    shift_start: str
    shift_end: str
    project_name: str


class SolarFarmList(BaseModel):
    farms: list[SolarFarmResponse]
    total_power_mw: float


class WindFarmList(BaseModel):
    farms: list[WindFarmResponse]
    total_power_mw: float


class BatteryList(BaseModel):
    batteries: list[BatteryResponse]
    total_capacity_mwh: float


class ConsumerList(BaseModel):
    consumers: list[ConsumerResponse]


class FactoryResponse(BaseModel):
    id: str
    priority: str
    base_mw: float
    day_mw: float
    start_hour: float
    end_hour: float
    project_name: str


class FactoryList(BaseModel):
    factories: list[FactoryResponse]


class GridResponse(BaseModel):
    pk: int
    line_limit_mw: float
    buy_premium_per_kwh: float
    price_cap_per_kwh: float
    emission_tco2_per_mwh: float
    project_name: str


class GridList(BaseModel):
    grids: list[GridResponse]


class ProjectDetail(BaseModel):
    id: int
    name: str
    solar_farms: list[SolarFarmResponse]
    wind_farms: list[WindFarmResponse]
    batteries: list[BatteryResponse]
    consumers: list[ConsumerResponse]
    factories: list[FactoryResponse]
    grids: list[GridResponse]
    total_solar_mw: float
    total_wind_mw: float
    total_battery_capacity_mwh: float
    is_complete: bool
    incomplete_reasons: list[str] = []


# ── events ──────────────────────────────────────────────────────────────

EVENT_TYPES = ("storm", "wind_lull", "cloud", "demand_spike", "price_spike", "maintenance")


class EventCreate(BaseModel):
    type: Literal["storm", "wind_lull", "cloud", "demand_spike", "price_spike", "maintenance"]
    targets: list[str]
    start_time: str
    end_time: str
    wind_speed_ms: float | None = None
    line_derate_mw: float | None = None
    pct_drop: float | None = None
    extra_mw: float | None = None
    multiplier: float | None = None
    visibility: Literal["alerted", "surprise"] = "alerted"
    alert_time: str | None = None
    source: Literal["manual", "inject", "preset"] = "manual"

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("Must be HH:MM format")
        h, m = map(int, v.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid time")
        return v

    @field_validator("alert_time")
    @classmethod
    def validate_alert_time(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("Must be HH:MM format")
        return v

    @model_validator(mode="after")
    def check_alert_required(self):
        if self.visibility == "alerted" and self.alert_time is None:
            raise ValueError("alert_time is required when visibility is 'alerted'")
        if self.alert_time is not None and self.start_time:
            if self.alert_time > self.start_time:
                raise ValueError("alert_time must be <= start_time")
        return self


class EventUpdate(BaseModel):
    end_time: str | None = None
    start_time: str | None = None
    targets: list[str] | None = None
    wind_speed_ms: float | None = None
    line_derate_mw: float | None = None
    pct_drop: float | None = None
    extra_mw: float | None = None
    multiplier: float | None = None
    visibility: Literal["alerted", "surprise"] | None = None
    alert_time: str | None = None


class EventResponse(BaseModel):
    id: int
    project_id: int
    type: str
    targets: list[str]
    start_time: str
    end_time: str
    wind_speed_ms: float | None
    line_derate_mw: float | None
    pct_drop: float | None
    extra_mw: float | None
    multiplier: float | None
    visibility: str
    alert_time: str | None
    source: str
    created_at: datetime | None

    model_config = {"from_attributes": True}


# ── simulation / run session ────────────────────────────────────────────


class StartDayRequest(BaseModel):
    mode: Literal["reliability", "profit", "clean"] = "reliability"
    seed: int = 42
    scenario: Literal["blank", "may_storm"] = "blank"


class RunSessionResponse(BaseModel):
    project_id: int
    status: str
    current_tick: int
    mode: str
    seed: int
    scenario: str
    speed: float

    model_config = {"from_attributes": True}


class TickResultResponse(BaseModel):
    tick: int
    timestamp: str
    actuals: dict
    dispatch: dict
    supervisor: dict
    battery_energy_mwh: float
    battery_soc_pct: float

    model_config = {"from_attributes": True}
