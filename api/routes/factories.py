from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Factory, Project
from api.schemas import FactoryCreate, FactoryList, FactoryResponse

router = APIRouter(prefix="/factories", tags=["factories"])


@router.post("/", response_model=FactoryResponse, status_code=201)
def create_factory(body: FactoryCreate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == body.project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{body.project_name}' not found")
    existing = (
        db.query(Factory)
        .filter(Factory.factory_id == body.id, Factory.project_id == project.id)
        .first()
    )
    if existing:
        raise HTTPException(400, f"Factory '{body.id}' already exists in project '{body.project_name}'")
    factory = Factory(
        factory_id=body.id,
        priority=body.priority,
        base_mw=body.base_mw,
        day_mw=body.day_mw,
        start_hour=body.start_hour,
        end_hour=body.end_hour,
        project_id=project.id,
    )
    db.add(factory)
    db.commit()
    return FactoryResponse(
        id=factory.factory_id,
        priority=factory.priority,
        base_mw=factory.base_mw,
        day_mw=factory.day_mw,
        start_hour=factory.start_hour,
        end_hour=factory.end_hour,
        project_name=project.name,
    )


@router.get("/", response_model=FactoryList)
def list_factories(project_name: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{project_name}' not found")
    factories = (
        db.query(Factory)
        .filter(Factory.project_id == project.id)
        .order_by(Factory.factory_id)
        .all()
    )
    return FactoryList(
        factories=[
            FactoryResponse(
                id=f.factory_id,
                priority=f.priority,
                base_mw=f.base_mw,
                day_mw=f.day_mw,
                start_hour=f.start_hour,
                end_hour=f.end_hour,
                project_name=project.name,
            )
            for f in factories
        ]
    )
