"""Seed the database with a project from a scenario YAML file."""
from __future__ import annotations

import yaml

from api.database import Base, SessionLocal, engine
from api.models import AssetStatus, Battery, Factory, Grid, Project, SolarFarm, WindFarm


def seed(yaml_path: str, project_name: str) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)

    db = SessionLocal()
    try:
        project = Project(name=project_name)
        db.add(project)
        db.flush()

        for sf in cfg.get("solar_farms", []):
            db.add(SolarFarm(
                farm_id=sf["id"],
                power_output_mw=sf["capacity_mw"],
                project_id=project.id,
            ))

        for wf in cfg.get("wind_farms", []):
            db.add(WindFarm(
                farm_id=wf["id"],
                power_output_mw=wf["capacity_mw"],
                project_id=project.id,
            ))

        bat = cfg.get("battery", {})
        if bat:
            db.add(Battery(
                battery_id="B1",
                total_capacity_mw=bat["capacity_mwh"],
                charge_discharge_rate_mwh=bat["max_charge_mw"],
                project_id=project.id,
            ))

        for fac in cfg.get("factories", []):
            db.add(Factory(
                factory_id=fac["id"],
                priority=fac["priority"],
                base_mw=fac["base_mw"],
                day_mw=fac["day_mw"],
                start_hour=fac["start_hour"],
                end_hour=fac["end_hour"],
                project_id=project.id,
            ))

        grid = cfg.get("grid", {})
        if grid:
            db.add(Grid(
                line_limit_mw=grid["line_limit_mw"],
                buy_premium_per_kwh=grid["buy_premium_per_kwh"],
                price_cap_per_kwh=grid["price_cap_per_kwh"],
                emission_tco2_per_mwh=grid["emission_tco2_per_mwh"],
                project_id=project.id,
            ))

        for sf in cfg.get("solar_farms", []):
            db.add(AssetStatus(
                project_id=project.id,
                asset_type="solar",
                asset_id=sf["id"],
                status="online",
            ))
        for wf in cfg.get("wind_farms", []):
            db.add(AssetStatus(
                project_id=project.id,
                asset_type="wind",
                asset_id=wf["id"],
                status="online",
            ))
        if bat:
            db.add(AssetStatus(
                project_id=project.id,
                asset_type="battery",
                asset_id="B1",
                status="online",
            ))

        db.commit()
        print(f"Seeded project '{project_name}' from {yaml_path}")
    finally:
        db.close()


if __name__ == "__main__":
    seed("scenarios/surplus.yaml", "farm 1")
