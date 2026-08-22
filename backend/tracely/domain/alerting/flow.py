"""DAG resolution for an alert rule's step flow. Pure — no I/O, no ORM.

The graph is React Flow's own `{nodes, edges}` JSON on `Monitor.flow_layout`, and this module is
the half of it the engine actually reads. Three stages, and the canvas implements the SAME three
(`frontend/app/lib/ruleFlow.ts`) — they must agree or a rule runs differently than it looked on
screen:

1. **Dedupe** edges by `source→target`; drop self-loops and edges naming unknown nodes.
2. **Reachability**: BFS from `__rule_trigger__`. Anything not reachable is NOT executed — an
   orphan node on the canvas is a *parked* step, not a silent failure.
3. **Kahn topological sort** over trigger ∪ reachable, popping ready nodes in sorted-id order so
   the result is deterministic across processes. A non-empty remainder means a cycle, which fails
   the whole run with a plain-English error rather than executing half a graph.

With no usable edges it falls back to `ORDER BY order_index` — that fallback is what makes a rule
created by the API (or by an older UI) still run.

`TRIGGER_NODE_ID` is declared here and again in the frontend constants. If you port one thing
verbatim, port this: it is the id of a node that exists on the canvas and in `edges`, but never as
a step row.
"""

from __future__ import annotations

import heapq
from collections import defaultdict, deque
from typing import Any, Iterable, Protocol

TRIGGER_NODE_ID = "__rule_trigger__"

CYCLE_ERROR = "Alert flow: cycle detected (steps cannot be ordered)."


class StepLike(Protocol):
    """What flow resolution needs from a step — the ORM row and a plain dataclass both fit."""

    id: str
    order_index: int


def _outgoing(edges_raw: Iterable[Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for e in edges_raw or []:
        if not isinstance(e, dict):
            continue
        src, tgt = e.get("source"), e.get("target")
        if not isinstance(src, str) or not isinstance(tgt, str) or src == tgt:
            continue
        if tgt not in out[src]:
            out[src].append(tgt)
    return out


def ordered_steps(steps: list[Any], flow_layout: dict | None) -> tuple[list[Any], str | None]:
    """Executable steps in run order, or `([], error)` on a cycle.

    Steps not reachable from the trigger are dropped — deliberately: they are saved, visible on
    the canvas, and parked.
    """
    items = list(steps or [])
    if not items:
        return [], None

    by_id = {str(s.id): s for s in items}
    edges_raw = (flow_layout or {}).get("edges") if isinstance(flow_layout, dict) else None
    if not isinstance(edges_raw, list):
        return sorted(items, key=lambda s: s.order_index), None

    out = _outgoing(edges_raw)

    reachable: set[str] = set()
    queue = deque([TRIGGER_NODE_ID])
    while queue:
        for tgt in out.get(queue.popleft(), []):
            if tgt in by_id and tgt not in reachable:
                reachable.add(tgt)
                queue.append(tgt)
    if not reachable:
        # An edge list that connects nothing to the trigger is indistinguishable from no edge list
        # at all — run the saved order rather than nothing.
        return sorted(items, key=lambda s: s.order_index), None

    nodes = {TRIGGER_NODE_ID} | reachable
    adj: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = dict.fromkeys(nodes, 0)
    for src in nodes:
        for tgt in out.get(src, []):
            if tgt in nodes:
                adj[src].append(tgt)
                indegree[tgt] += 1

    order, err = _kahn(nodes, adj, indegree)
    if err:
        return [], err
    return [by_id[i] for i in order if i in reachable], None


def _kahn(
    nodes: set[str], adj: dict[str, list[str]], indegree: dict[str, int]
) -> tuple[list[str], str | None]:
    """Kahn's algorithm with sorted-id tie-breaks, so two processes emit the same order."""
    heap = [n for n in sorted(nodes) if indegree[n] == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        nid = heapq.heappop(heap)
        order.append(nid)
        for nb in sorted(adj.get(nid, [])):
            indegree[nb] -= 1
            if indegree[nb] == 0:
                heapq.heappush(heap, nb)
    if len(order) != len(nodes):
        return [], CYCLE_ERROR
    return order, None


def ancestor_step_ids(
    step_id: str, edges_raw: list[dict] | None, execution_order_ids: list[str]
) -> list[str]:
    """The steps whose output THIS step can read, in execution order.

    Upstream outputs are **positional, not keyed by id**: the engine sets
    `ctx["steps"] = [{"result": …} for each ancestor]`, so `steps[0]` means "my first upstream step
    on this branch". Two parallel branches each see their own `steps[0]`. The canvas's "Prior
    steps" chips are built from this same reverse BFS — the chip label IS the runtime path, and if
    the two implementations drift every template silently reads the wrong value.
    """
    if not edges_raw:
        if step_id not in execution_order_ids:
            return []
        pos = execution_order_ids.index(step_id)
        return [s for s in execution_order_ids[:pos] if s != TRIGGER_NODE_ID]

    incoming: dict[str, list[str]] = defaultdict(list)
    for e in edges_raw:
        if not isinstance(e, dict):
            continue
        src, tgt = e.get("source"), e.get("target")
        if isinstance(src, str) and isinstance(tgt, str):
            incoming[tgt].append(src)

    allowed = set(execution_order_ids)
    ancestors: set[str] = set()
    seen: set[str] = set()
    queue = deque([step_id])
    while queue:
        cur = queue.popleft()
        if cur in seen:
            continue
        seen.add(cur)
        for src in incoming.get(cur, []):
            if src == TRIGGER_NODE_ID or src not in allowed:
                continue
            ancestors.add(src)
            queue.append(src)

    index_of = {sid: i for i, sid in enumerate(execution_order_ids)}
    return sorted(ancestors, key=lambda x: index_of.get(x, len(execution_order_ids)))


def flow_layout_error(raw: dict | None) -> str | None:
    """The one shape guarantee the API enforces on an otherwise opaque layout blob."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return "flow_layout must be a JSON object"
    edges = raw.get("edges")
    if edges is None:
        return None
    if not isinstance(edges, list):
        return "flow_layout.edges must be a list when present"
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            return f"flow_layout.edges[{i}] must be an object"
        if not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str):
            return f"flow_layout.edges[{i}] requires string `source` and `target`"
    return None


def linear_flow_layout(steps: list[tuple[str, str, str]], *, trigger_label: str) -> dict:
    """A React-Flow layout that chains the trigger through `steps` (id, name, step_type).

    Used when a rule has steps but no layout — an API-created rule then opens on the canvas
    looking exactly like one drawn by hand.
    """
    nodes: list[dict] = [
        {
            "id": TRIGGER_NODE_ID,
            "type": "trigger",
            "position": {"x": 60, "y": 140},
            "data": {"label": trigger_label},
        }
    ]
    edges: list[dict] = []
    prev = TRIGGER_NODE_ID
    for i, (sid, name, step_type) in enumerate(steps):
        nodes.append(
            {
                "id": sid,
                "type": "ruleStep",
                "position": {"x": 360 + i * 300, "y": 140},
                "data": {"name": name, "step_type": step_type},
            }
        )
        edges.append({"id": f"e-{prev}-{sid}", "source": prev, "target": sid})
        prev = sid
    return {"nodes": nodes, "edges": edges}
