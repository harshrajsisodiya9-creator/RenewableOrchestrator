from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Battery, Consumer, Grid, Project, SolarFarm, WindFarm
from api.schemas import (
    BatteryResponse,
    ConsumerResponse,
    FactoryResponse,
    GridResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectFullCreate,
    ProjectResponse,
    SolarFarmResponse,
    WindFarmResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    if db.query(Project).filter(Project.name == body.name).first():
        raise HTTPException(400, f"Project '{body.name}' already exists")
    project = Project(name=body.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.post("/full", response_model=ProjectDetail, status_code=201)
def create_project_full(body: ProjectFullCreate, db: Session = Depends(get_db)):
    if db.query(Project).filter(Project.name == body.name).first():
        raise HTTPException(400, f"Project '{body.name}' already exists")

    project = Project(name=body.name)
    db.add(project)
    db.flush()

    for sf in body.solar_farms:
        db.add(SolarFarm(
            farm_id=sf.id,
            power_output_mw=sf.power_output_mw,
            project_id=project.id,
        ))

    for wf in body.wind_farms:
        db.add(WindFarm(
            farm_id=wf.id,
            power_output_mw=wf.power_output_mw,
            project_id=project.id,
        ))

    for bat in body.batteries:
        db.add(Battery(
            battery_id=bat.id,
            total_capacity_mw=bat.capacity_mwh,
            charge_discharge_rate_mwh=bat.max_rate_mw,
            min_soc_pct=bat.min_soc_pct,
            max_soc_pct=bat.max_soc_pct,
            initial_soc_pct=bat.initial_soc_pct,
            project_id=project.id,
        ))

    for con in body.consumers:
        db.add(Consumer(
            consumer_id=con.id,
            day_load_mw=con.day_load_mw,
            night_load_mw=con.night_load_mw,
            shift_start=con.shift_start,
            shift_end=con.shift_end,
            project_id=project.id,
        ))

    if body.grid:
        db.add(Grid(
            line_limit_mw=body.grid.line_limit_mw,
            buy_premium_per_kwh=body.grid.buy_premium_per_kwh,
            price_cap_per_kwh=body.grid.price_cap_per_kwh,
            emission_tco2_per_mwh=body.grid.emission_tco2_per_mwh,
            project_id=project.id,
        ))

    db.commit()
    db.refresh(project)
    return _build_project_detail(project)


@router.get("/", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.id).all()


@router.get("/{project_name}", response_model=ProjectDetail)
def get_project(project_name: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{project_name}' not found")
    return _build_project_detail(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).get(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    db.delete(project)
    db.commit()


def _build_project_detail(project: Project) -> ProjectDetail:
    solar_farms = [
        SolarFarmResponse(id=f.farm_id, power_output_mw=f.power_output_mw, project_name=project.name)
        for f in project.solar_farms
    ]
    wind_farms = [
        WindFarmResponse(id=f.farm_id, power_output_mw=f.power_output_mw, project_name=project.name)
        for f in project.wind_farms
    ]
    batteries = [
        BatteryResponse(
            id=b.battery_id,
            capacity_mwh=b.total_capacity_mw,
            max_rate_mw=b.charge_discharge_rate_mwh,
            min_soc_pct=b.min_soc_pct,
            max_soc_pct=b.max_soc_pct,
            initial_soc_pct=b.initial_soc_pct,
            project_name=project.name,
        )
        for b in project.batteries
    ]
    consumers = [
        ConsumerResponse(
            id=c.consumer_id,
            day_load_mw=c.day_load_mw,
            night_load_mw=c.night_load_mw,
            shift_start=c.shift_start,
            shift_end=c.shift_end,
            project_name=project.name,
        )
        for c in project.consumers
    ]
    factories = [
        FactoryResponse(
            id=f.factory_id,
            priority=f.priority,
            base_mw=f.base_mw,
            day_mw=f.day_mw,
            start_hour=f.start_hour,
            end_hour=f.end_hour,
            project_name=project.name,
        )
        for f in project.factories
    ]
    grids = [
        GridResponse(
            pk=g.pk,
            line_limit_mw=g.line_limit_mw,
            buy_premium_per_kwh=g.buy_premium_per_kwh,
            price_cap_per_kwh=g.price_cap_per_kwh,
            emission_tco2_per_mwh=g.emission_tco2_per_mwh,
            project_name=project.name,
        )
        for g in project.grids
    ]

    reasons: list[str] = []
    has_consumers = len(project.consumers) > 0
    has_grid = len(project.grids) > 0
    line_limit = project.grids[0].line_limit_mw if project.grids else None
    has_supply = (
        len(project.solar_farms) > 0
        or len(project.wind_farms) > 0
        or len(project.batteries) > 0
        or (line_limit is not None and line_limit > 0)
    )

    if not has_consumers:
        reasons.append("No consumers defined")
    if not has_grid:
        reasons.append("No grid / line limit defined")
    if not has_supply:
        reasons.append("No supply path (needs a farm, battery, or line limit > 0)")

    return ProjectDetail(
        id=project.id,
        name=project.name,
        solar_farms=solar_farms,
        wind_farms=wind_farms,
        batteries=batteries,
        consumers=consumers,
        factories=factories,
        grids=grids,
        total_solar_mw=sum(f.power_output_mw for f in project.solar_farms),
        total_wind_mw=sum(f.power_output_mw for f in project.wind_farms),
        total_battery_capacity_mwh=sum(b.total_capacity_mw for b in project.batteries),
        is_complete=len(reasons) == 0,
        incomplete_reasons=reasons,
    )
