"""Thread-safe singleton for sharing runtime state between the graph loop and API."""

from __future__ import annotations

import threading


class RunState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_tick: int = 0
        self._running: bool = False
        self._project_id: int | None = None
        self._project_locks: dict[int, threading.Lock] = {}

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

    def acquire_project(self, project_id: int) -> bool:
        with self._lock:
            if project_id not in self._project_locks:
                self._project_locks[project_id] = threading.Lock()
            lock = self._project_locks[project_id]
        return lock.acquire(blocking=False)

    def release_project(self, project_id: int) -> None:
        with self._lock:
            lock = self._project_locks.get(project_id)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                pass


run_state = RunState()
