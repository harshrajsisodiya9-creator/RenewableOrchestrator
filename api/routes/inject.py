"""POST /inject endpoint for runtime fault injection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Battery, Project, SolarFarm, WindFarm
from api.schemas import InjectRequest, InjectResponse
from graph.asset_status import restore_asset, trip_asset
from graph.run_state import run_state

router = APIRouter(tags=["inject"])

_ASSET_TABLE = {
    "solar": (SolarFarm, "farm_id"),
    "wind": (WindFarm, "farm_id"),
    "battery": (Battery, "battery_id"),
}


@router.post("/inject", response_model=InjectResponse, status_code=200)
def inject_fault(body: InjectRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == body.project_name).first()
    if not project:
        raise HTTPException(404, f"Project '{body.project_name}' not found")

    model, id_col = _ASSET_TABLE.get(body.asset_type, (None, None))
    if model is None:
        raise HTTPException(400, f"Invalid asset_type '{body.asset_type}'")

    asset = (
        db.query(model)
        .filter(
            getattr(model, id_col) == body.asset_id,
            model.project_id == project.id,
        )
        .first()
    )
    if not asset:
        raise HTTPException(
            404,
            f"{body.asset_type} asset '{body.asset_id}' not found in project '{body.project_name}'",
        )

    current_tick = run_state.get_tick()

    if body.action == "trip":
        result = trip_asset(
            project_id=project.id,
            asset_type=body.asset_type,
            asset_id=body.asset_id,
            current_tick=current_tick,
            duration_ticks=body.duration_ticks,
        )
        msg = f"{body.asset_type}/{body.asset_id} tripped at tick {current_tick}"
        if body.duration_ticks:
            msg += f", auto-restore at tick {current_tick + body.duration_ticks}"
    else:
        result = restore_asset(
            project_id=project.id,
            asset_type=body.asset_type,
            asset_id=body.asset_id,
        )
        msg = f"{body.asset_type}/{body.asset_id} restored at tick {current_tick}"

    return InjectResponse(
        asset_type=result["asset_type"],
        asset_id=result["asset_id"],
        status=result["status"],
        tripped_at=result["tripped_at"],
        restore_at=result["restore_at"],
        message=msg,
    )
