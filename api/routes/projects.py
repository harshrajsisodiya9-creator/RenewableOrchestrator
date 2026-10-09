from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Project
from api.schemas import (
    BatteryResponse,
    FactoryResponse,
    GridResponse,
    ProjectCreate,
    ProjectDetail,
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


@router.get("/", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.id).all()


@router.get("/{project_name}", response_model=ProjectDetail)
def get_project(project_name: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{project_name}' not found")

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
            total_capacity_mw=b.total_capacity_mw,
            charge_discharge_rate_mwh=b.charge_discharge_rate_mwh,
            project_name=project.name,
        )
        for b in project.batteries
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

    return ProjectDetail(
        id=project.id,
        name=project.name,
        solar_farms=solar_farms,
        wind_farms=wind_farms,
        batteries=batteries,
        factories=factories,
        grids=grids,
        total_solar_mw=sum(f.power_output_mw for f in project.solar_farms),
        total_wind_mw=sum(f.power_output_mw for f in project.wind_farms),
        total_battery_capacity_mw=sum(b.total_capacity_mw for b in project.batteries),
    )
