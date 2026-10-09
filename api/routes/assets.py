from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Battery, Project, SolarFarm, WindFarm
from api.schemas import (
    BatteryCreate,
    BatteryList,
    BatteryResponse,
    SolarFarmCreate,
    SolarFarmList,
    SolarFarmResponse,
    WindFarmCreate,
    WindFarmList,
    WindFarmResponse,
)

router = APIRouter(tags=["assets"])


def _get_project(db: Session, project_name: str) -> Project:
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{project_name}' not found")
    return project


# ── solar farms ──────────────────────────────────────────────────────────


@router.post("/solar-farms", response_model=SolarFarmResponse, status_code=201)
def create_solar_farm(body: SolarFarmCreate, db: Session = Depends(get_db)):
    project = _get_project(db, body.project_name)
    existing = (
        db.query(SolarFarm)
        .filter(SolarFarm.farm_id == body.id, SolarFarm.project_id == project.id)
        .first()
    )
    if existing:
        raise HTTPException(400, f"Solar farm '{body.id}' already exists in project '{body.project_name}'")
    farm = SolarFarm(
        farm_id=body.id,
        power_output_mw=body.power_output_mw,
        project_id=project.id,
    )
    db.add(farm)
    db.commit()
    return SolarFarmResponse(id=farm.farm_id, power_output_mw=farm.power_output_mw, project_name=project.name)


@router.get("/solar-farms", response_model=SolarFarmList)
def list_solar_farms(project_name: str, db: Session = Depends(get_db)):
    project = _get_project(db, project_name)
    farms = (
        db.query(SolarFarm)
        .filter(SolarFarm.project_id == project.id)
        .order_by(SolarFarm.farm_id)
        .all()
    )
    items = [
        SolarFarmResponse(id=f.farm_id, power_output_mw=f.power_output_mw, project_name=project.name)
        for f in farms
    ]
    return SolarFarmList(farms=items, total_power_mw=sum(f.power_output_mw for f in farms))


# ── wind farms ───────────────────────────────────────────────────────────


@router.post("/wind-farms", response_model=WindFarmResponse, status_code=201)
def create_wind_farm(body: WindFarmCreate, db: Session = Depends(get_db)):
    project = _get_project(db, body.project_name)
    existing = (
        db.query(WindFarm)
        .filter(WindFarm.farm_id == body.id, WindFarm.project_id == project.id)
        .first()
    )
    if existing:
        raise HTTPException(400, f"Wind farm '{body.id}' already exists in project '{body.project_name}'")
    farm = WindFarm(
        farm_id=body.id,
        power_output_mw=body.power_output_mw,
        project_id=project.id,
    )
    db.add(farm)
    db.commit()
    return WindFarmResponse(id=farm.farm_id, power_output_mw=farm.power_output_mw, project_name=project.name)


@router.get("/wind-farms", response_model=WindFarmList)
def list_wind_farms(project_name: str, db: Session = Depends(get_db)):
    project = _get_project(db, project_name)
    farms = (
        db.query(WindFarm)
        .filter(WindFarm.project_id == project.id)
        .order_by(WindFarm.farm_id)
        .all()
    )
    items = [
        WindFarmResponse(id=f.farm_id, power_output_mw=f.power_output_mw, project_name=project.name)
        for f in farms
    ]
    return WindFarmList(farms=items, total_power_mw=sum(f.power_output_mw for f in farms))


# ── batteries ────────────────────────────────────────────────────────────


@router.post("/batteries", response_model=BatteryResponse, status_code=201)
def create_battery(body: BatteryCreate, db: Session = Depends(get_db)):
    project = _get_project(db, body.project_name)
    existing = (
        db.query(Battery)
        .filter(Battery.battery_id == body.id, Battery.project_id == project.id)
        .first()
    )
    if existing:
        raise HTTPException(400, f"Battery '{body.id}' already exists in project '{body.project_name}'")
    battery = Battery(
        battery_id=body.id,
        total_capacity_mw=body.total_capacity_mw,
        charge_discharge_rate_mwh=body.charge_discharge_rate_mwh,
        project_id=project.id,
    )
    db.add(battery)
    db.commit()
    return BatteryResponse(
        id=battery.battery_id,
        total_capacity_mw=battery.total_capacity_mw,
        charge_discharge_rate_mwh=battery.charge_discharge_rate_mwh,
        project_name=project.name,
    )


@router.get("/batteries", response_model=BatteryList)
def list_batteries(project_name: str, db: Session = Depends(get_db)):
    project = _get_project(db, project_name)
    batteries = (
        db.query(Battery)
        .filter(Battery.project_id == project.id)
        .order_by(Battery.battery_id)
        .all()
    )
    items = [
        BatteryResponse(
            id=b.battery_id,
            total_capacity_mw=b.total_capacity_mw,
            charge_discharge_rate_mwh=b.charge_discharge_rate_mwh,
            project_name=project.name,
        )
        for b in batteries
    ]
    return BatteryList(batteries=items, total_capacity_mw=sum(b.total_capacity_mw for b in batteries))
