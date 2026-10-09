"""Thread-safe singleton for sharing runtime state between the graph loop and API."""

from __future__ import annotations

import threading


class RunState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_tick: int = 0
        self._running: bool = False
        self._project_id: int | None = None

    def set_tick(self, tick: int) -> None:
        with self._lock:
            self._current_tick = tick

    def get_tick(self) -> int:
        with self._lock:
            return self._current_tick

    def set_running(self, project_id: int) -> None:
        with self._lock:
            self._running = True
            self._project_id = project_id

    def set_stopped(self) -> None:
        with self._lock:
            self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def project_id(self) -> int | None:
        with self._lock:
            return self._project_id


run_state = RunState()
