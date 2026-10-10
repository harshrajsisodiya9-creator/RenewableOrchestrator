from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Battery, Consumer, Project, SolarFarm, WindFarm
from api.schemas import (
    BatteryCreate,
    BatteryList,
    BatteryResponse,
    ConsumerCreate,
    ConsumerList,
    ConsumerResponse,
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
        total_capacity_mw=body.capacity_mwh,
        charge_discharge_rate_mwh=body.max_rate_mw,
        min_soc_pct=body.min_soc_pct,
        max_soc_pct=body.max_soc_pct,
        initial_soc_pct=body.initial_soc_pct,
        project_id=project.id,
    )
    db.add(battery)
    db.commit()
    return BatteryResponse(
        id=battery.battery_id,
        capacity_mwh=battery.total_capacity_mw,
        max_rate_mw=battery.charge_discharge_rate_mwh,
        min_soc_pct=battery.min_soc_pct,
        max_soc_pct=battery.max_soc_pct,
        initial_soc_pct=battery.initial_soc_pct,
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
            capacity_mwh=b.total_capacity_mw,
            max_rate_mw=b.charge_discharge_rate_mwh,
            min_soc_pct=b.min_soc_pct,
            max_soc_pct=b.max_soc_pct,
            initial_soc_pct=b.initial_soc_pct,
            project_name=project.name,
        )
        for b in batteries
    ]
    return BatteryList(batteries=items, total_capacity_mwh=sum(b.total_capacity_mw for b in batteries))


# ── consumers ────────────────────────────────────────────────────────────


@router.post("/consumers", response_model=ConsumerResponse, status_code=201)
def create_consumer(body: ConsumerCreate, db: Session = Depends(get_db)):
    project = _get_project(db, body.project_name)
    existing = (
        db.query(Consumer)
        .filter(Consumer.consumer_id == body.id, Consumer.project_id == project.id)
        .first()
    )
    if existing:
        raise HTTPException(400, f"Consumer '{body.id}' already exists in project '{body.project_name}'")
    consumer = Consumer(
        consumer_id=body.id,
        day_load_mw=body.day_load_mw,
        night_load_mw=body.night_load_mw,
        shift_start=body.shift_start,
        shift_end=body.shift_end,
        project_id=project.id,
    )
    db.add(consumer)
    db.commit()
    return ConsumerResponse(
        id=consumer.consumer_id,
        day_load_mw=consumer.day_load_mw,
        night_load_mw=consumer.night_load_mw,
        shift_start=consumer.shift_start,
        shift_end=consumer.shift_end,
        project_name=project.name,
    )


@router.get("/consumers", response_model=ConsumerList)
def list_consumers(project_name: str, db: Session = Depends(get_db)):
    project = _get_project(db, project_name)
    consumers = (
        db.query(Consumer)
        .filter(Consumer.project_id == project.id)
        .order_by(Consumer.consumer_id)
        .all()
    )
    return ConsumerList(
        consumers=[
            ConsumerResponse(
                id=c.consumer_id,
                day_load_mw=c.day_load_mw,
                night_load_mw=c.night_load_mw,
                shift_start=c.shift_start,
                shift_end=c.shift_end,
                project_name=project.name,
            )
            for c in consumers
        ]
    )
