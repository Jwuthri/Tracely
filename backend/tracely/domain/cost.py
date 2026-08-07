"""Per-span cost, from token counts and a per-million-token rate. Pure — no I/O, no table.

Cost is not something instrumentors trace: no provider puts a price on the wire, so the only way
to have a money column is `tokens x rate`. The *rate* is not our business to maintain — OpenRouter
publishes the whole catalog and keeps it current, so it is fetched at startup and looked up in
`infrastructure/llm/provider.resolve_rate`. This module is only the arithmetic.

Before this existed, `cost_details` was never written and every server-side cost figure — Trends,
analytics, the gate's spend deltas — summed an always-empty map to a hard zero.
"""

from __future__ import annotations

Rate = tuple[float | None, float | None]


def cost_details(rate: Rate | None, usage: dict[str, int] | None) -> dict[str, float]:
    """`{"input": usd, "output": usd}` for one span — the shape the `cost_details` column stores.

    Empty when the model has no published price or the span carries no tokens, so an unpriced run
    never masquerades as a free one: a 0.0 would silently under-report a project's whole spend.
    Keys mirror `usage_details` so the two maps line up, and values are summed leaf-wise
    downstream (`arraySum(mapValues(cost_details))`) — so only non-overlapping components go in.
    """
    if not usage or rate is None:
        return {}
    per_in, per_out = rate
    out: dict[str, float] = {}
    for key, per_mtok in (("input", per_in), ("output", per_out)):
        tokens = usage.get(key) or 0
        if tokens and per_mtok:
            out[key] = round(tokens * per_mtok / 1_000_000.0, 12)
    # A span that reported only a `total` still deserves a number. Price it at the input rate —
    # the conservative side, since output is never the cheaper of the two.
    if not out and usage.get("total") and per_in:
        out["total"] = round(usage["total"] * per_in / 1_000_000.0, 12)
    return out
