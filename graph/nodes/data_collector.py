"""LangGraph node: reads the simulator for the current tick and populates State."""

from __future__ import annotations

from graph.models.state import State
from graph.simulator import Simulator

_simulator: Simulator | None = None


def init_simulator(sim: Simulator) -> None:
    """Call once at startup to inject the shared Simulator instance."""
    global _simulator
    _simulator = sim


def data_collector(state: State) -> dict:
    """Observe the world at the current tick and return State updates.

    If ``tick`` is not yet set in the state, starts at 0.
    """
    if _simulator is None:
        raise RuntimeError(
            "Simulator not initialised — call init_simulator() before "
            "running the graph."
        )

    tick = state.get("tick", 0)
    obs = _simulator.observe(tick)

    # carry forward config fields that don't come from the simulator
    return obs
