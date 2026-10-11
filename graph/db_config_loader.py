"""Load asset configs from PostgreSQL and build a Simulator-compatible config dict."""

from __future__ import annotations

import yaml

from api.database import SessionLocal
from api.models import Battery, Factory, Grid, Project, SolarFarm, WindFarm

PHYSICS_PATH = "config/physics_defaults.yaml"


def load_config_from_db(project_name: str) -> dict:
    with open(PHYSICS_PATH) as f:
        cfg: dict = yaml.safe_load(f)

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.name == project_name).first()
        if project is None:
            raise ValueError(f"Project '{project_name}' not found in database")

        solar_farms = (
            db.query(SolarFarm)
            .filter(SolarFarm.project_id == project.id)
            .order_by(SolarFarm.farm_id)
            .all()
        )
        cfg["solar_farms"] = [
            {"id": f.farm_id, "capacity_mw": f.power_output_mw}
            for f in solar_farms
        ]
        cfg["solar"]["total_capacity_mw"] = sum(
            f.power_output_mw for f in solar_farms
        )

        wind_farms = (
            db.query(WindFarm)
            .filter(WindFarm.project_id == project.id)
            .order_by(WindFarm.farm_id)
            .all()
        )
        cfg["wind_farms"] = [
            {"id": f.farm_id, "capacity_mw": f.power_output_mw}
            for f in wind_farms
        ]
        cfg["wind"]["total_capacity_mw"] = sum(
            f.power_output_mw for f in wind_farms
        )

        batteries = (
            db.query(Battery)
            .filter(Battery.project_id == project.id)
            .order_by(Battery.battery_id)
            .all()
        )
        cfg["battery_ids"] = [{"id": b.battery_id} for b in batteries]
        if batteries:
            cfg["battery"]["capacity_mwh"] = sum(b.total_capacity_mw for b in batteries)
            cfg["battery"]["max_charge_mw"] = sum(b.charge_discharge_rate_mwh for b in batteries)
            cfg["battery"]["max_discharge_mw"] = sum(b.charge_discharge_rate_mwh for b in batteries)
        else:
            cfg["battery"]["capacity_mwh"] = 0.0
            cfg["battery"]["max_charge_mw"] = 0.0
            cfg["battery"]["max_discharge_mw"] = 0.0
            cfg["battery"]["soc_init_pct"] = 0.0

        factories = (
            db.query(Factory)
            .filter(Factory.project_id == project.id)
            .order_by(Factory.factory_id)
            .all()
        )
        cfg["factories"] = [
            {
                "id": f.factory_id,
                "priority": f.priority,
                "base_mw": f.base_mw,
                "day_mw": f.day_mw,
                "start_hour": f.start_hour,
                "end_hour": f.end_hour,
            }
            for f in factories
        ]

        grid = db.query(Grid).filter(Grid.project_id == project.id).first()
        if grid:
            cfg["grid"] = {
                "line_limit_mw": grid.line_limit_mw,
                "buy_premium_per_kwh": grid.buy_premium_per_kwh,
                "price_cap_per_kwh": grid.price_cap_per_kwh,
                "emission_tco2_per_mwh": grid.emission_tco2_per_mwh,
            }
        else:
            cfg["grid"] = {
                "line_limit_mw": 0.0,
                "buy_premium_per_kwh": 0.0,
                "price_cap_per_kwh": 10.0,
                "emission_tco2_per_mwh": 0.0,
            }

        cfg["_project_id"] = project.id
        return cfg
    finally:
        db.close()
