from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    solar_farms: Mapped[list[SolarFarm]] = relationship(back_populates="project", cascade="all, delete-orphan")
    wind_farms: Mapped[list[WindFarm]] = relationship(back_populates="project", cascade="all, delete-orphan")
    batteries: Mapped[list[Battery]] = relationship(back_populates="project", cascade="all, delete-orphan")
    consumers: Mapped[list[Consumer]] = relationship(back_populates="project", cascade="all, delete-orphan")
    factories: Mapped[list[Factory]] = relationship(back_populates="project", cascade="all, delete-orphan")
    grids: Mapped[list[Grid]] = relationship(back_populates="project", cascade="all, delete-orphan")


class SolarFarm(Base):
    __tablename__ = "solar_farm"
    __table_args__ = (
        UniqueConstraint("farm_id", "project_id", name="uq_solar_project"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    farm_id: Mapped[str] = mapped_column(String, nullable=False)
    power_output_mw: Mapped[float] = mapped_column(Float, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)

    project: Mapped[Project] = relationship(back_populates="solar_farms")


class WindFarm(Base):
    __tablename__ = "wind_farm"
    __table_args__ = (
        UniqueConstraint("farm_id", "project_id", name="uq_wind_project"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    farm_id: Mapped[str] = mapped_column(String, nullable=False)
    power_output_mw: Mapped[float] = mapped_column(Float, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)

    project: Mapped[Project] = relationship(back_populates="wind_farms")


class Battery(Base):
    __tablename__ = "battery"
    __table_args__ = (
        UniqueConstraint("battery_id", "project_id", name="uq_battery_project"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    battery_id: Mapped[str] = mapped_column(String, nullable=False)
    total_capacity_mw: Mapped[float] = mapped_column(Float, nullable=False)
    charge_discharge_rate_mwh: Mapped[float] = mapped_column(Float, nullable=False)
    min_soc_pct: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    max_soc_pct: Mapped[float] = mapped_column(Float, nullable=False, default=95.0)
    initial_soc_pct: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)

    project: Mapped[Project] = relationship(back_populates="batteries")


class Consumer(Base):
    __tablename__ = "consumer"
    __table_args__ = (
        UniqueConstraint("consumer_id", "project_id", name="uq_consumer_project"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consumer_id: Mapped[str] = mapped_column(String, nullable=False)
    day_load_mw: Mapped[float] = mapped_column(Float, nullable=False)
    night_load_mw: Mapped[float] = mapped_column(Float, nullable=False)
    shift_start: Mapped[str] = mapped_column(String, nullable=False, default="06:00")
    shift_end: Mapped[str] = mapped_column(String, nullable=False, default="22:00")
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)

    project: Mapped[Project] = relationship(back_populates="consumers")


class Factory(Base):
    __tablename__ = "factory"
    __table_args__ = (
        UniqueConstraint("factory_id", "project_id", name="uq_factory_project"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factory_id: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    base_mw: Mapped[float] = mapped_column(Float, nullable=False)
    day_mw: Mapped[float] = mapped_column(Float, nullable=False)
    start_hour: Mapped[float] = mapped_column(Float, nullable=False)
    end_hour: Mapped[float] = mapped_column(Float, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)

    project: Mapped[Project] = relationship(back_populates="factories")


class Grid(Base):
    __tablename__ = "grid"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    line_limit_mw: Mapped[float] = mapped_column(Float, nullable=False)
    buy_premium_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    price_cap_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    emission_tco2_per_mwh: Mapped[float] = mapped_column(Float, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)

    project: Mapped[Project] = relationship(back_populates="grids")


class AssetStatus(Base):
    __tablename__ = "asset_status"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "asset_type", "asset_id", name="uq_asset_status"
        ),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    asset_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="online")
    tripped_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    restore_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
