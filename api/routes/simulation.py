"""Simulation control endpoints: start day, reset, play/pause/speed/step/status."""

from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Event, Project, RunSession, TickResult
from api.schemas import RunSessionResponse, StartDayRequest, TickResultResponse

router = APIRouter(prefix="/projects/{project_id}/simulation", tags=["simulation"])

_runners: dict[int, "_ProjectRunner"] = {}
_runners_lock = threading.Lock()


def _hhmm_to_tick(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 4 + m // 15


def _tick_to_hhmm(tick: int) -> str:
    h = tick // 4
    m = (tick % 4) * 15
    return f"{h:02d}:{m:02d}"


def _get_project(project_id: int, db: Session) -> Project:
    project = db.query(Project).get(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


def _load_consumers_into_config(cfg: dict, project_id: int) -> None:
    from api.database import SessionLocal
    from api.models import Consumer

    db = SessionLocal()
    try:
        consumers = (
            db.query(Consumer)
            .filter(Consumer.project_id == project_id)
            .order_by(Consumer.consumer_id)
            .all()
        )
        for c in consumers:
            h_start, m_start = map(int, c.shift_start.split(":"))
            h_end, m_end = map(int, c.shift_end.split(":"))
            start_hour = h_start + m_start / 60.0
            end_hour = h_end + m_end / 60.0
            cfg.setdefault("factories", []).append({
                "id": c.consumer_id,
                "priority": "standard",
                "base_mw": c.night_load_mw,
                "day_mw": c.day_load_mw - c.night_load_mw,
                "start_hour": start_hour,
                "end_hour": end_hour,
            })
    finally:
        db.close()


def _load_scenario_events(project_id: int, scenario: str) -> None:
    """Load preset scenario events into the Event table."""
    if scenario == "blank":
        return

    import yaml

    scenario_files = {
        "may_storm": "config/scenarios/may_storm.yaml",
    }
    path = scenario_files.get(scenario)
    if not path or not os.path.exists(path):
        return

    from api.database import SessionLocal

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    db = SessionLocal()
    try:
        for ev in data.get("storm_events", []):
            db.add(Event(
                project_id=project_id,
                type="storm",
                targets=[],
                start_time=ev["storm_start"],
                end_time=ev["storm_end"],
                wind_speed_ms=ev.get("wind_speed_ms"),
                line_derate_mw=ev.get("line_limit_mw"),
                visibility="alerted",
                alert_time=ev.get("alert_time"),
                source="preset",
            ))
        for ev in data.get("maintenance_windows", []):
            db.add(Event(
                project_id=project_id,
                type="maintenance",
                targets=[ev["asset"]],
                start_time=ev["start"],
                end_time=ev["end"],
                visibility="alerted",
                alert_time=ev["start"],
                source="preset",
            ))
        db.commit()
    finally:
        db.close()


class _ProjectRunner:
    """Manages graph execution for one project in a background thread."""

    def __init__(self, project_id: int, cfg: dict, session_pk: int):
        self.project_id = project_id
        self.cfg = cfg
        self.session_pk = session_pk
        self._playing = threading.Event()
        self._stop = threading.Event()
        self._step_event = threading.Event()
        self._speed: float = 1.0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._playing.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._playing.clear()

    def resume(self) -> None:
        self._playing.set()

    def step(self) -> None:
        self._step_event.set()

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.25, min(speed, 16.0))

    def stop(self) -> None:
        self._stop.set()
        self._playing.set()
        self._step_event.set()

    @property
    def speed(self) -> float:
        return self._speed

    def _wait_for_play(self) -> bool:
        while not self._playing.is_set() and not self._stop.is_set():
            if self._step_event.wait(timeout=0.5):
                self._step_event.clear()
                return True
        return not self._stop.is_set()

    def _run(self) -> None:
        from graph.db_config_loader import load_config_from_db
        from graph.graph import compile_graph, get_checkpointer
        from graph.nodes.data_collector import init_data_collector_db, init_simulator
        from graph.nodes.executor import init_executor_simulator
        from graph.run_state import run_state
        from graph.simulator import Simulator

        from api.database import SessionLocal

        cfg = self.cfg
        project_id = self.project_id

        sim = Simulator(cfg)
        init_simulator(sim)
        init_executor_simulator(sim)

        init_data_collector_db(
            project_id,
            cfg.get("solar_farms", []),
            cfg.get("wind_farms", []),
            wind_physics=cfg.get("wind"),
        )

        cp = get_checkpointer()
        thread_id = str(project_id)
        try:
            cp.delete_thread(thread_id)
        except Exception:
            pass

        graph = compile_graph(use_checkpointer=True)
        config = {"configurable": {"thread_id": thread_id}}

        defaults = cfg.get("defaults", {})
        state: dict = {
            "mode": defaults.get("mode", "reliability"),
            "reserve_floor_pct": defaults.get("reserve_floor_pct", 20.0),
            "carbon_price_per_tonne": defaults.get("carbon_price_per_tonne", 500.0),
            "curtail_penalty_per_kwh": defaults.get("curtail_penalty_per_kwh", 0.30),
            "tick_log": [],
            "retry_count": 0,
            "project_id": project_id,
            "session_id": self.session_pk,
        }

        run_state.set_running(project_id)
        try:
            for tick in range(96):
                if self._stop.is_set():
                    break

                if not self._playing.is_set():
                    if not self._wait_for_play():
                        break

                run_state.set_tick(tick)
                state["tick"] = tick
                state["retry_count"] = 0
                state["violations"] = []
                result = graph.invoke(state, config)
                state.update(result)

                self._save_tick_result(tick, state)
                self._update_session(tick)

                delay = 1.0 / self._speed
                if not self._stop.wait(timeout=delay):
                    pass

            self._finish_session("completed" if not self._stop.is_set() else "stopped")
        except Exception as e:
            import logging
            logging.getLogger("simulation").exception("Runner failed for project %d", project_id)
            self._finish_session("error")
        finally:
            run_state.set_stopped()
            run_state.release_project(project_id)
            with _runners_lock:
                _runners.pop(project_id, None)

    def _save_tick_result(self, tick: int, state: dict) -> None:
        from api.database import SessionLocal

        action = state.get("validated_action") or state.get("plan")
        price = state.get("price_per_kwh", 0)
        buy_mw = getattr(action, "buy", 0)
        sell_mw = getattr(action, "sell", 0)
        buy_cost = buy_mw * 0.25 * (price + 0.50) * 1000
        sell_income = sell_mw * 0.25 * price * 1000
        violations = state.get("violations", [])

        actuals = {
            "solar_mw": state.get("solar_mw", 0),
            "wind_mw": state.get("wind_mw", 0),
            "demand_mw": state.get("demand_mw", 0),
            "renewables_mw": state.get("renewables_mw", 0),
            "price_per_kwh": price,
            "wind_speed_ms": state.get("wind_speed_ms", 0),
            "line_limit_mw": state.get("line_limit_mw", 0),
            "active_storm": state.get("active_storm", False),
        }
        dispatch = {
            "charge": getattr(action, "charge", 0),
            "discharge": getattr(action, "discharge", 0),
            "buy": buy_mw,
            "sell": sell_mw,
            "curtail": getattr(action, "curtail", 0),
            "unmet": getattr(action, "unmet", 0),
            "cash_cost_inr": round(buy_cost - sell_income, 2),
            "carbon_tonnes": round(buy_mw * 0.25 * 0.71, 4),
        }
        supervisor = {
            "called": state.get("should_call_supervisor", False),
            "risk_level": state.get("risk_level", ""),
            "reserve_target_pct": state.get("reserve_target_pct", 0),
            "strategy_reason": state.get("strategy_reason", ""),
            "plan_status": state.get("plan_status", ""),
            "monitor_triggers": state.get("monitor_triggers", []),
            "violations": [v.detail for v in violations] if violations else [],
        }

        db = SessionLocal()
        try:
            existing = (
                db.query(TickResult)
                .filter(TickResult.project_id == self.project_id, TickResult.tick == tick)
                .first()
            )
            if existing:
                existing.actuals = actuals
                existing.dispatch = dispatch
                existing.supervisor = supervisor
                existing.battery_energy_mwh = state.get("battery_energy_mwh", 0)
                existing.battery_soc_pct = state.get("battery_soc_pct", 0)
            else:
                db.add(TickResult(
                    project_id=self.project_id,
                    tick=tick,
                    timestamp=_tick_to_hhmm(tick),
                    actuals=actuals,
                    dispatch=dispatch,
                    supervisor=supervisor,
                    battery_energy_mwh=state.get("battery_energy_mwh", 0),
                    battery_soc_pct=state.get("battery_soc_pct", 0),
                ))
            db.commit()
        finally:
            db.close()

    def _update_session(self, tick: int) -> None:
        from api.database import SessionLocal

        db = SessionLocal()
        try:
            session = db.query(RunSession).get(self.session_pk)
            if session:
                session.current_tick = tick
                session.speed = self._speed
                db.commit()
        finally:
            db.close()

    def _finish_session(self, status: str) -> None:
        from api.database import SessionLocal

        db = SessionLocal()
        try:
            session = db.query(RunSession).get(self.session_pk)
            if session:
                session.status = status
                db.commit()
        finally:
            db.close()


@router.post("/start", response_model=RunSessionResponse)
def start_day(project_id: int, body: StartDayRequest, db: Session = Depends(get_db)):
    project = _get_project(project_id, db)

    has_consumers = len(project.consumers) > 0
    has_grid = len(project.grids) > 0
    line_limit = project.grids[0].line_limit_mw if project.grids else None
    has_supply = (
        len(project.solar_farms) > 0
        or len(project.wind_farms) > 0
        or len(project.batteries) > 0
        or (line_limit is not None and line_limit > 0)
    )
    if not (has_consumers and has_grid and has_supply):
        raise HTTPException(400, "Project is incomplete — cannot start simulation")

    with _runners_lock:
        if project_id in _runners:
            raise HTTPException(409, "Simulation already running for this project")

    existing = db.query(RunSession).filter(RunSession.project_id == project_id).first()
    if existing:
        db.delete(existing)
        db.flush()

    db.query(TickResult).filter(TickResult.project_id == project_id).delete()
    db.query(Event).filter(
        Event.project_id == project_id, Event.source == "preset"
    ).delete()
    db.flush()

    _load_scenario_events(project_id, body.scenario)

    session = RunSession(
        project_id=project_id,
        status="playing",
        current_tick=0,
        mode=body.mode,
        seed=body.seed,
        scenario=body.scenario,
        speed=1.0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    from graph.db_config_loader import load_config_from_db

    cfg = load_config_from_db(project.name)
    cfg.pop("_project_id", None)
    _load_consumers_into_config(cfg, project_id)

    cfg.setdefault("defaults", {})["seed"] = body.seed
    cfg["defaults"]["mode"] = body.mode

    from graph.run_state import run_state

    if not run_state.acquire_project(project_id):
        raise HTTPException(409, "Project lock held by another run")

    runner = _ProjectRunner(project_id, cfg, session.pk)
    with _runners_lock:
        _runners[project_id] = runner
    runner.start()

    return session


@router.post("/reset", response_model=dict)
def reset_day(project_id: int, db: Session = Depends(get_db)):
    _get_project(project_id, db)

    with _runners_lock:
        runner = _runners.get(project_id)
        if runner:
            runner.stop()

    db.query(TickResult).filter(TickResult.project_id == project_id).delete()
    db.query(Event).filter(
        Event.project_id == project_id, Event.source == "preset"
    ).delete()
    session = db.query(RunSession).filter(RunSession.project_id == project_id).first()
    if session:
        db.delete(session)
    db.commit()

    return {"status": "reset", "project_id": project_id}


@router.post("/pause", response_model=dict)
def pause_simulation(project_id: int, db: Session = Depends(get_db)):
    with _runners_lock:
        runner = _runners.get(project_id)
    if not runner:
        raise HTTPException(404, "No active simulation for this project")
    runner.pause()
    session = db.query(RunSession).filter(RunSession.project_id == project_id).first()
    if session:
        session.status = "paused"
        db.commit()
    return {"status": "paused"}


@router.post("/play", response_model=dict)
def play_simulation(project_id: int, db: Session = Depends(get_db)):
    with _runners_lock:
        runner = _runners.get(project_id)
    if not runner:
        raise HTTPException(404, "No active simulation for this project")
    runner.resume()
    session = db.query(RunSession).filter(RunSession.project_id == project_id).first()
    if session:
        session.status = "playing"
        db.commit()
    return {"status": "playing"}


@router.post("/step", response_model=dict)
def step_simulation(project_id: int):
    with _runners_lock:
        runner = _runners.get(project_id)
    if not runner:
        raise HTTPException(404, "No active simulation for this project")
    runner.step()
    return {"status": "stepped"}


@router.post("/speed", response_model=dict)
def set_speed(project_id: int, speed: float = 1.0, db: Session = Depends(get_db)):
    with _runners_lock:
        runner = _runners.get(project_id)
    if not runner:
        raise HTTPException(404, "No active simulation for this project")
    runner.set_speed(speed)
    session = db.query(RunSession).filter(RunSession.project_id == project_id).first()
    if session:
        session.speed = runner.speed
        db.commit()
    return {"status": "speed_set", "speed": runner.speed}


@router.get("/status", response_model=RunSessionResponse)
def get_simulation_status(project_id: int, db: Session = Depends(get_db)):
    _get_project(project_id, db)
    session = db.query(RunSession).filter(RunSession.project_id == project_id).first()
    if not session:
        raise HTTPException(404, "No simulation session for this project")
    return session


@router.get("/ticks", response_model=list[TickResultResponse])
def get_tick_results(
    project_id: int,
    after: int = -1,
    db: Session = Depends(get_db),
):
    _get_project(project_id, db)
    return (
        db.query(TickResult)
        .filter(TickResult.project_id == project_id, TickResult.tick > after)
        .order_by(TickResult.tick)
        .all()
    )
