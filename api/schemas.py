from __future__ import annotations

import re

from typing import Literal

from pydantic import BaseModel, field_validator


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
    total_capacity_mw: float
    charge_discharge_rate_mwh: float
    project_name: str

    @field_validator("id")
    @classmethod
    def validate_battery_id(cls, v: str) -> str:
        if not re.fullmatch(r"B\d+", v):
            raise ValueError("Battery ID must match pattern B1, B2, ...")
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
    total_capacity_mw: float
    charge_discharge_rate_mwh: float
    project_name: str


class SolarFarmList(BaseModel):
    farms: list[SolarFarmResponse]
    total_power_mw: float


class WindFarmList(BaseModel):
    farms: list[WindFarmResponse]
    total_power_mw: float


class BatteryList(BaseModel):
    batteries: list[BatteryResponse]
    total_capacity_mw: float


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
    factories: list[FactoryResponse]
    grids: list[GridResponse]
    total_solar_mw: float
    total_wind_mw: float
    total_battery_capacity_mw: float
