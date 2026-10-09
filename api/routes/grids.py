from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Grid, Project
from api.schemas import GridCreate, GridList, GridResponse

router = APIRouter(prefix="/grids", tags=["grids"])


@router.post("/", response_model=GridResponse, status_code=201)
def create_grid(body: GridCreate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == body.project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{body.project_name}' not found")
    grid = Grid(
        line_limit_mw=body.line_limit_mw,
        buy_premium_per_kwh=body.buy_premium_per_kwh,
        price_cap_per_kwh=body.price_cap_per_kwh,
        emission_tco2_per_mwh=body.emission_tco2_per_mwh,
        project_id=project.id,
    )
    db.add(grid)
    db.commit()
    db.refresh(grid)
    return GridResponse(
        pk=grid.pk,
        line_limit_mw=grid.line_limit_mw,
        buy_premium_per_kwh=grid.buy_premium_per_kwh,
        price_cap_per_kwh=grid.price_cap_per_kwh,
        emission_tco2_per_mwh=grid.emission_tco2_per_mwh,
        project_name=project.name,
    )


@router.get("/", response_model=GridList)
def list_grids(project_name: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{project_name}' not found")
    grids = db.query(Grid).filter(Grid.project_id == project.id).all()
    return GridList(
        grids=[
            GridResponse(
                pk=g.pk,
                line_limit_mw=g.line_limit_mw,
                buy_premium_per_kwh=g.buy_premium_per_kwh,
                price_cap_per_kwh=g.price_cap_per_kwh,
                emission_tco2_per_mwh=g.emission_tco2_per_mwh,
                project_name=project.name,
            )
            for g in grids
        ]
    )
