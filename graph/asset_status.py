"""CRUD operations for the asset_status table."""

from __future__ import annotations

from api.database import SessionLocal
from api.models import AssetStatus


def read_asset_statuses(project_id: int) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AssetStatus)
            .filter(AssetStatus.project_id == project_id)
            .all()
        )
        return [
            {
                "asset_type": r.asset_type,
                "asset_id": r.asset_id,
                "status": r.status,
                "tripped_at": r.tripped_at,
                "restore_at": r.restore_at,
            }
            for r in rows
        ]
    finally:
        db.close()


def trip_asset(
    project_id: int,
    asset_type: str,
    asset_id: str,
    current_tick: int,
    duration_ticks: int | None = None,
    reason: str = "",
) -> dict:
    restore_at = current_tick + duration_ticks if duration_ticks else None
    db = SessionLocal()
    try:
        row = (
            db.query(AssetStatus)
            .filter(
                AssetStatus.project_id == project_id,
                AssetStatus.asset_type == asset_type,
                AssetStatus.asset_id == asset_id,
            )
            .first()
        )
        if row is None:
            raise ValueError(f"No asset_status row for {asset_type}/{asset_id}")
        row.status = "tripped"
        row.tripped_at = current_tick
        row.restore_at = restore_at
        row.reason = reason
        db.commit()
        return {
            "asset_type": row.asset_type,
            "asset_id": row.asset_id,
            "status": row.status,
            "tripped_at": row.tripped_at,
            "restore_at": row.restore_at,
        }
    finally:
        db.close()


def restore_asset(project_id: int, asset_type: str, asset_id: str) -> dict:
    db = SessionLocal()
    try:
        row = (
            db.query(AssetStatus)
            .filter(
                AssetStatus.project_id == project_id,
                AssetStatus.asset_type == asset_type,
                AssetStatus.asset_id == asset_id,
            )
            .first()
        )
        if row is None:
            raise ValueError(f"No asset_status row for {asset_type}/{asset_id}")
        row.status = "online"
        row.tripped_at = None
        row.restore_at = None
        row.reason = None
        db.commit()
        return {
            "asset_type": row.asset_type,
            "asset_id": row.asset_id,
            "status": row.status,
            "tripped_at": None,
            "restore_at": None,
        }
    finally:
        db.close()


def auto_restore_expired(project_id: int, current_tick: int) -> list[str]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AssetStatus)
            .filter(
                AssetStatus.project_id == project_id,
                AssetStatus.status == "tripped",
                AssetStatus.restore_at.isnot(None),
                AssetStatus.restore_at <= current_tick,
            )
            .all()
        )
        restored: list[str] = []
        for row in rows:
            row.status = "online"
            row.tripped_at = None
            row.restore_at = None
            row.reason = None
            restored.append(f"{row.asset_type}/{row.asset_id}")
        if restored:
            db.commit()
        return restored
    finally:
        db.close()


def seed_asset_statuses(
    project_id: int,
    solar_ids: list[str],
    wind_ids: list[str],
    battery_ids: list[str],
    grid_ids: list[str] | None = None,
) -> None:
    if grid_ids is None:
        grid_ids = ["grid"]
    db = SessionLocal()
    try:
        for asset_type, ids in [
            ("solar", solar_ids),
            ("wind", wind_ids),
            ("battery", battery_ids),
            ("grid", grid_ids),
        ]:
            for asset_id in ids:
                exists = (
                    db.query(AssetStatus)
                    .filter(
                        AssetStatus.project_id == project_id,
                        AssetStatus.asset_type == asset_type,
                        AssetStatus.asset_id == asset_id,
                    )
                    .first()
                )
                if not exists:
                    db.add(AssetStatus(
                        project_id=project_id,
                        asset_type=asset_type,
                        asset_id=asset_id,
                        status="online",
                    ))
        db.commit()
    finally:
        db.close()
