"""CRUD endpoints for simulation events under /projects/{project_id}/events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Event, Project, RunSession
from api.schemas import EventCreate, EventResponse, EventUpdate

router = APIRouter(prefix="/projects/{project_id}/events", tags=["events"])


def _hhmm_to_tick(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 4 + m // 15


def _get_project(project_id: int, db: Session) -> Project:
    project = db.query(Project).get(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


def _current_tick(project_id: int, db: Session) -> int:
    session = db.query(RunSession).filter(RunSession.project_id == project_id).first()
    if session and session.status in ("playing", "paused"):
        return session.current_tick
    return 0


@router.post("/", response_model=EventResponse, status_code=201)
def create_event(project_id: int, body: EventCreate, db: Session = Depends(get_db)):
    _get_project(project_id, db)
    event = Event(
        project_id=project_id,
        type=body.type,
        targets=body.targets,
        start_time=body.start_time,
        end_time=body.end_time,
        wind_speed_ms=body.wind_speed_ms,
        line_derate_mw=body.line_derate_mw,
        pct_drop=body.pct_drop,
        extra_mw=body.extra_mw,
        multiplier=body.multiplier,
        visibility=body.visibility,
        alert_time=body.alert_time,
        source=body.source,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/", response_model=list[EventResponse])
def list_events(project_id: int, db: Session = Depends(get_db)):
    _get_project(project_id, db)
    return (
        db.query(Event)
        .filter(Event.project_id == project_id)
        .order_by(Event.start_time)
        .all()
    )


@router.get("/{event_id}", response_model=EventResponse)
def get_event(project_id: int, event_id: int, db: Session = Depends(get_db)):
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.project_id == project_id)
        .first()
    )
    if not event:
        raise HTTPException(404, "Event not found")
    return event


@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    project_id: int, event_id: int, body: EventUpdate, db: Session = Depends(get_db)
):
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.project_id == project_id)
        .first()
    )
    if not event:
        raise HTTPException(404, "Event not found")

    current = _current_tick(project_id, db)
    start_tick = _hhmm_to_tick(event.start_time)
    end_tick = _hhmm_to_tick(event.end_time)

    if current >= end_tick:
        raise HTTPException(400, "Cannot edit an event that has fully ended")

    if current >= start_tick:
        allowed = {"end_time"}
        provided = {k for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        forbidden = provided - allowed
        if forbidden:
            raise HTTPException(
                400,
                f"Event is ongoing — only end_time can be changed. "
                f"Cannot update: {', '.join(sorted(forbidden))}",
            )

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if value is not None:
            setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=204)
def delete_event(project_id: int, event_id: int, db: Session = Depends(get_db)):
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.project_id == project_id)
        .first()
    )
    if not event:
        raise HTTPException(404, "Event not found")

    current = _current_tick(project_id, db)
    start_tick = _hhmm_to_tick(event.start_time)

    if current >= start_tick:
        raise HTTPException(400, "Cannot delete an event that has started or ended")

    db.delete(event)
    db.commit()
