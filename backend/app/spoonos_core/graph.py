from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List
import copy


@dataclass
class TraceEvent:
    node: str
    input: Dict[str, Any]
    output: Dict[str, Any]
    started_at: str
    ended_at: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node": self.node,
            "input": self.input,
            "output": self.output,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
        }


class Node:
    name = "node"

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Node.run must be implemented")


class GraphAgent:
    def __init__(
        self,
        nodes: Dict[str, Node],
        edges: Dict[str, List[str]],
        entry_node: str,
        exit_nodes: List[str],
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.exit_nodes = set(exit_nodes)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        trace: List[Dict[str, Any]] = []
        current = self.entry_node
        ctx = dict(context)

        while current:
            node = self.nodes[current]
            ctx["trace"] = trace
            started_at = _utc_now()
            try:
                output = node.run(ctx) or {}
                status = "ok"
            except Exception as exc:  # pragma: no cover - surfaced in trace
                output = {"error": str(exc)}
                status = "error"
            ended_at = _utc_now()

            trace_event = TraceEvent(
                node=node.name,
                input=copy.deepcopy(ctx),
                output=copy.deepcopy(output),
                started_at=started_at,
                ended_at=ended_at,
                status=status,
            )
            trace.append(trace_event.to_dict())

            ctx.update(output)
            ctx["trace"] = trace

            if current in self.exit_nodes:
                break

            next_nodes = self.edges.get(current, [])
            current = next_nodes[0] if next_nodes else None

        ctx["trace"] = trace
        return ctx


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
class StateGraph:
    """Small local compatibility wrapper for the subset of StateGraph used by this app."""

    def __init__(self, state_schema: Any | None = None) -> None:
        self.state_schema = state_schema
        self.nodes: Dict[str, Any] = {}
        self.edges: Dict[str, List[str]] = {}
        self.entry_point: str | None = None

    def add_node(self, name: str, node: Any) -> None:
        self.nodes[name] = node

    def add_edge(self, source: str, target: str) -> None:
        self.edges.setdefault(source, []).append(target)

    def set_entry_point(self, name: str) -> None:
        self.entry_point = name

    def compile(self) -> "_CompiledStateGraph":
        if not self.entry_point:
            raise ValueError("StateGraph entry point is not set")
        return _CompiledStateGraph(
            nodes=self.nodes,
            edges=self.edges,
            entry_point=self.entry_point,
        )


class _CompiledStateGraph:
    def __init__(
        self,
        nodes: Dict[str, Any],
        edges: Dict[str, List[str]],
        entry_point: str,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.entry_point = entry_point

    async def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        ctx = dict(state)
        current = self.entry_point
        visited_count = 0
        max_steps = max(len(self.nodes) + 5, 10)

        while current:
            if current not in self.nodes:
                raise KeyError(f"Unknown graph node: {current}")

            visited_count += 1
            if visited_count > max_steps:
                raise RuntimeError("StateGraph execution exceeded max steps")

            node = self.nodes[current]
            output = node(ctx)

            if hasattr(output, "__await__"):
                output = await output

            if output:
                ctx.update(output)

            next_nodes = self.edges.get(current, [])
            current = next_nodes[0] if next_nodes else None

        return ctx