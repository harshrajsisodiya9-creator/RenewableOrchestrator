"""LangGraph StateGraph wiring for the Renewable Energy Orchestrator."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from graph.models.state import State
from graph.nodes.data_collector import data_collector
from graph.nodes.executor import executor
from graph.nodes.logger import logger
from graph.nodes.monitor import monitor
from graph.nodes.optimizer import optimizer
from graph.nodes.supervisor import supervisor
from graph.nodes.validator import validator

workflow = StateGraph(State)

# ── register nodes ────────────────────────────────────────────────────────
workflow.add_node("data_collector", data_collector)
workflow.add_node("monitor", monitor)
workflow.add_node("supervisor", supervisor)
workflow.add_node("optimizer", optimizer)
workflow.add_node("validator", validator)
workflow.add_node("executor", executor)
workflow.add_node("logger", logger)

# ── entry point ───────────────────────────────────────────────────────────
workflow.set_entry_point("data_collector")

# ── edges ─────────────────────────────────────────────────────────────────
workflow.add_edge("data_collector", "monitor")

workflow.add_conditional_edges(
    "monitor",
    lambda s: "supervisor" if s.get("should_call_supervisor") else "optimizer",
    {"supervisor": "supervisor", "optimizer": "optimizer"},
)

workflow.add_edge("supervisor", "optimizer")
workflow.add_edge("optimizer", "validator")

# allow one retry loop through supervisor when validation fails
workflow.add_conditional_edges(
    "validator",
    lambda s: (
        "supervisor"
        if not s.get("validation_passed") and s.get("retry_count", 0) < 1
        else "executor"
    ),
    {"supervisor": "supervisor", "executor": "executor"},
)

workflow.add_edge("executor", "logger")
workflow.add_edge("logger", END)

graph = workflow.compile()
