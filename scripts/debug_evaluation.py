"""Step through how an evaluation column runs on one conversation (or one turn).

Usage (from repo root, with `make infra-up` running):
    uv run python scripts/debug_evaluation.py --list                     # recent conversations
    uv run python scripts/debug_evaluation.py --evaluators               # the columns
    uv run python scripts/debug_evaluation.py --thread-id <ID>           # run every column
    uv run python scripts/debug_evaluation.py --thread-id <ID> --column faithfulness
    uv run python scripts/debug_evaluation.py --thread-id <ID> --dry-run # grade, persist nothing
    uv run python scripts/debug_evaluation.py --trace-id <ID>            # one turn only
    uv run python scripts/debug_evaluation.py --thread-id <ID> --break-on-llm
    uv run python scripts/debug_evaluation.py --thread-id <ID> --full    # untruncated prompts

Recording is OFF here: the script prints everything already, so it would only add an internal
trace per run to the workspace you are debugging. `--record` opts back in.

Granularity — three levels: Conversation, Message, Step (SPAN/TOOL/GENERATION/CHAIN are all
Step, differing only in which span types get graded). The level lives on the evaluator ROW (the
UI's level dropdown), so trying another one normally means another column. `--level` overrides
it for one run, in memory:
    … --level CONVERSATION --dry-run              # Conversation: one grade for the whole thread
    … --level AGENT_RUN --dry-run                 # Message: one grade per turn
    … --level SPAN --span-types AGENT --dry-run   # Step: one grade per step, your span types
The `sends:` line printed per evaluator says exactly what each level puts in the prompt.

This drives the REAL path — `EvaluationService.evaluate_thread`, the same call the UI's Play
button makes (`POST /api/evaluations/run`) and the same engine ingest runs. Nothing is
reimplemented here; the script only taps it and prints:

  1. the specs selected (kind/level/output_type/threshold/model/mode) and, per spec, which
     judge branch it will take + whether on-INGEST targeting would have kept it
  2. the turns in the thread, oldest first
  3. every LLM call: system prompt, user message, response schema, model → the raw verdict
  4. every persisted score frame (byte-for-byte what the SSE run endpoint streams to the grid)

Connections come from `tracely.config.Settings` (reads `.env`) — see the header of
`debug_failure_clustering.py` for the docker port-forwarding notes.

Where to set breakpoints
------------------------
  backend/tracely/services/evaluation_service.py       EvaluationService.evaluate_thread   <- turn loop, sequential chaining
                                                       EvaluationService._dispatch_specs   <- topo sort, deps injection, per-spec try
  backend/tracely/domain/evaluation/evaluators/llm_judge.py
                                                       LLMJudgeEvaluator.run               <- the level -> branch fork
                                                       _run_trace/_run_steps/_run_conversation/_run_advanced
                                                       _call_and_build                     <- prompt assembled, before the model call
                                                       _to_result/_json_result             <- verdict + threshold mapping
  backend/tracely/domain/evaluation/template_resolver.py  template_resolver.resolve        <- @VARIABLE substitution (advanced columns)

Or skip editing files: `--break-before` drops into pdb before the run (`s` to step in),
`--break-on-llm` drops in at each model call with the assembled prompt in scope.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap

from sqlalchemy import text

from tracely.config import settings
from tracely.domain.evaluation.evaluators.base import (
    CHAIN,
    CONVERSATION,
    GENERATION,
    RUN,
    SPAN,
    STEP_LEVELS,
    TOOL,
)
from tracely.domain.evaluation.targeting import spec_applies
from tracely.domain.evaluation.template_resolver import (
    extract_template_variables,
    references_conversation_scope,
)
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.clickhouse import client as clickhouse
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.llm import provider

TRUNC = 1200  # per prompt block, unless --full

# Three levels in the product's vocabulary (mirrors LEVEL_LABEL in frontend/app/lib/evaluators.ts).
# SPAN/TOOL/GENERATION/CHAIN are all "Step" — they differ only in which span types get graded.
LEVEL_LABEL = {CONVERSATION: "Conversation", RUN: "Message"} | {lv: "Step" for lv in STEP_LEVELS}


def rule(title: str) -> None:
    print(f"\n{'─' * 100}\n{title}\n{'─' * 100}")


def block(label: str, body: str, full: bool) -> None:
    body = body or "(empty)"
    if not full and len(body) > TRUNC:
        body = body[:TRUNC] + f"\n… [{len(body) - TRUNC} more chars — rerun with --full]"
    print(f"  {label}:")
    print(textwrap.indent(body, "    | "))


def resolve_project_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    with SyncSessionLocal() as s:
        rows = s.execute(text("SELECT id, name FROM projects ORDER BY created_at LIMIT 5")).all()
    if not rows:
        sys.exit("no projects in Postgres — run `make seed` first")
    if len(rows) > 1:
        print(f"multiple projects, using the oldest: {rows[0].name} ({rows[0].id})")
    return rows[0].id


def list_threads(project_id: str, limit: int = 20) -> None:
    """Recent conversations — copy-paste fodder for --thread-id."""
    rows = clickhouse.get_client().query(
        """
        SELECT if(conversation_id = '', trace_id, conversation_id) AS thread_id,
               uniq(trace_id) AS turns, max(start_time) AS last_seen
        FROM events FINAL WHERE project_id = {p:String}
        GROUP BY thread_id ORDER BY last_seen DESC LIMIT {n:UInt32}
        """,
        parameters={"p": project_id, "n": limit},
    ).result_rows
    if not rows:
        print("no traces — run `make demo` or `make seed-demo` first")
        return
    print(f"{'thread_id':<40}  {'turns':>5}  last_seen")
    for tid, turns, ts in rows:
        print(f"{tid:<40}  {turns:>5}  {ts}")


def branch_for(spec: dict) -> str:
    """Which method inside LLMJudgeEvaluator.run() this spec will land in."""
    if spec["kind"] != "llm_judge":
        return f"structural check={spec['config'].get('check')!r} (no LLM)"
    advanced = " (advanced/template)" if spec["config"].get("is_advanced") else ""
    if spec["config"].get("is_advanced"):
        return ("_run_advanced_steps — one grade per step" if spec["level"] in STEP_LEVELS
                else "_run_advanced — one grade for the " +
                     ("thread" if spec["level"] == CONVERSATION else "turn"))
    if spec["level"] == CONVERSATION:
        return "_run_conversation — one grade over the whole transcript" + advanced
    if spec["level"] in STEP_LEVELS:
        return "_run_steps — one grade per step (max_spans cap)" + advanced
    return "_run_trace — one grade per turn (request vs answer + tool grounding)" + advanced


def sends_for(spec: dict) -> str:
    """Exactly what lands in the user message at this level — the answer to "why didn't the
    judge see my tool call?". Mirrors `_run_conversation` / `_run_trace` / `_run_steps`."""
    if spec["kind"] != "llm_judge":
        return "nothing (structural checks read the spans directly, no prompt)"
    cfg = spec["config"] or {}
    if cfg.get("is_advanced"):
        return "whatever your @VARIABLE template resolves to — you own the context"
    if spec["level"] == CONVERSATION:
        return ("per turn: user request + FINAL answer only (each clipped 800 chars, whole "
                "transcript 8000). NO steps, NO tool I/O")
    if spec["level"] in STEP_LEVELS:
        types = cfg.get("span_types") or ["TOOL", "GENERATION"]
        scope = f"span_types={types}" if spec["level"] == SPAN else f"{spec['level']} spans only"
        return (f"one call PER step ({scope}, needs input or output, max_spans="
                f"{cfg.get('max_spans') or 30}): user request (1200) + that step's input (1500) "
                "+ output (1500)")
    return ("user request (2000) + final answer (2000) + every TOOL span's OUTPUT (600 each). "
            "NO step inputs, NO GENERATION/CHAIN bodies, NO tool arguments")


def describe_specs(specs: list[dict], root: dict, trace_id: str) -> None:
    rule(f"{len(specs)} evaluator(s) selected")
    for s in specs:
        cfg = s["config"] or {}
        print(f"\n▸ {s['score_name']}  [{s['kind']} · {LEVEL_LABEL.get(s['level'], '?')} "
              f"({s['level']})]  id={s['id']}")
        print(f"    branch      : {branch_for(s)}")
        print(f"    sends       : {textwrap.fill(sends_for(s), 92, subsequent_indent=' ' * 18)}")
        if s["kind"] == "llm_judge":
            print(f"    output_type : {cfg.get('output_type') or 'score'}   "
                  f"threshold={cfg.get('threshold', '0.6 (default)')}   "
                  f"model={cfg.get('model') or provider.default_model_id()}")
            print(f"    mode        : {cfg.get('execution_mode') or 'batch'}"
                  f"{'   depends_on=' + str(cfg['depends_on']) if cfg.get('depends_on') else ''}")
            if cfg.get("is_advanced"):
                wanted = cfg.get("template_variables") or extract_template_variables(cfg.get("prompt") or "")
                print(f"    variables   : {wanted or '(none)'}"
                      f"{'   ← conversation-scoped: whole thread gets fetched' if references_conversation_scope(wanted) else ''}")
        # The on-demand path (what this script and the Play button use) always grades. This is
        # what the AUTO on-ingest path would have decided for this trace.
        keep = spec_applies(s, agent_id=root.get("agent_id") or "", agent_slug="",
                            env=root.get("env") or "", trace_id=trace_id)
        print(f"    on-ingest   : {'would run' if keep else 'WOULD BE SKIPPED'} "
              f"(target_agent={s['target_agent'] or '*'} target_env={s['target_env'] or '*'} "
              f"sampling={s['sampling']})")


def install_taps(full: bool, break_on_llm: bool) -> None:
    """Wrap the two provider entry points every judge funnels through, so each model call
    prints its assembled prompt and the verdict it produced. Monkeypatching the module
    attribute is enough — llm_judge calls `provider.run_structured_agent(...)`."""
    real_structured, real_text = provider.run_structured_agent, provider.run_text_agent
    n = 0

    def show(kind: str, prompt: str, system_prompt: str | None, model: str | None, schema: str) -> None:
        nonlocal n
        n += 1
        rule(f"LLM call #{n} — {kind}  model={model or provider.default_model_id()}  schema={schema}")
        block("system prompt (the rubric)", system_prompt or "(none)", full)
        block("user message (the graded content)", prompt, full)

    def tapped_structured(prompt, *, response_format, system_prompt=None, model=None, **kw):
        show("structured", prompt, system_prompt, model, response_format.__name__)
        if break_on_llm:
            print("  --break-on-llm: pdb — `prompt` / `system_prompt` are in scope, `c` to send")
            breakpoint()
        out = real_structured(prompt, response_format=response_format,
                              system_prompt=system_prompt, model=model, **kw)
        print(f"  → verdict: {out.model_dump()}")
        return out

    def tapped_text(prompt, *, system_prompt=None, model=None, **kw):
        show("text", prompt, system_prompt, model, "free-form JSON")
        if break_on_llm:
            breakpoint()
        out = real_text(prompt, system_prompt=system_prompt, model=model, **kw)
        print(f"  → reply: {out[:500]}")
        return out

    provider.run_structured_agent = tapped_structured
    provider.run_text_agent = tapped_text


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--thread-id", help="conversation to evaluate (every turn + conversation columns)")
    p.add_argument("--trace-id", help="single turn instead of a whole conversation")
    p.add_argument("--column", action="append", default=[],
                   help="only this score_name (repeatable); default = every enabled evaluator")
    p.add_argument("--level", choices=[CONVERSATION, RUN, SPAN, TOOL, GENERATION, CHAIN],
                   help="grade at THIS level instead of the column's configured one (in-memory "
                        "only — the evaluator row is untouched). Use with --dry-run.")
    p.add_argument("--span-types", nargs="+", metavar="TYPE",
                   help="for --level SPAN: which span types to grade (default TOOL GENERATION)")
    p.add_argument("--project-id", help="override the default (first) project")
    p.add_argument("--dry-run", action="store_true", help="grade but persist nothing (no scores, no clusters)")
    p.add_argument("--full", action="store_true", help="print prompts untruncated")
    p.add_argument(
        "--record", action="store_true",
        help="also write the run as an internal trace (off by default — debugging should not add "
             "rows to the workspace you are inspecting)",
    )
    p.add_argument("--break-before", action="store_true", help="pdb before the run — `s` steps into the service")
    p.add_argument("--break-on-llm", action="store_true", help="pdb at each model call, prompt in scope")
    p.add_argument("--list", action="store_true", help="list recent conversations and exit")
    p.add_argument("--evaluators", action="store_true", help="list the project's enabled columns and exit")
    args = p.parse_args()

    # This script PRINTS every prompt, response and score below. Recording the same run as a trace
    # too (`domain/introspection.py`) would write one internal trace per invocation into the very
    # workspace you are debugging — debugging an eval should not add rows to the data you are
    # looking at. `--record` opts back in if you specifically want to inspect the recording itself.
    if not args.record:
        settings.introspection_enabled = False

    from tracely.services.evaluation_service import EvaluationService

    project_id = resolve_project_id(args.project_id)
    print(f"project_id = {project_id}")
    print(f"pg = {settings.database_url}")
    print(f"ch = {settings.clickhouse_host}:{settings.clickhouse_port}/{settings.clickhouse_database}")
    print(f"llm = {'enabled' if provider.llm_enabled() else 'DISABLED (no key — llm_judge columns return nothing)'}")

    if args.list:
        list_threads(project_id)
        return

    specs = EvaluationService.load_enabled_evaluators(project_id)
    if args.evaluators:
        for s in specs:
            print(f"{s['score_name']:<30}  {s['kind']:<12}  {s['level']:<13}  {s['id']}")
        if not specs:
            print("no enabled evaluators — create one in the UI (Evaluators) or run `make demo`")
        return
    if args.column:
        wanted = {c.lower() for c in args.column}
        specs = [s for s in specs if s["score_name"].lower() in wanted]
    if not specs:
        sys.exit("no matching enabled evaluators (try --evaluators)")
    if args.level or args.span_types:
        # The level lives on the evaluator ROW (that's what the UI's level dropdown sets), so
        # trying another granularity normally means another column. Here it's a per-run override.
        for s in specs:
            if args.level:
                s["level"] = args.level
            if args.span_types:
                s["config"] = {**(s["config"] or {}), "span_types": [t.upper() for t in args.span_types]}
        if not args.dry_run:
            print("\n!! --level/--span-types WITHOUT --dry-run: a step-level grade writes one score "
                  "per span_id, so the column's real cells change. Add --dry-run to just look.")
    if not args.thread_id and not args.trace_id:
        sys.exit("--thread-id or --trace-id required (or --list / --evaluators)")

    reader = TraceReader()
    thread_id = args.thread_id or args.trace_id
    trace_ids = [args.trace_id] if args.trace_id else reader.thread_trace_ids(project_id, thread_id)
    if not trace_ids:
        sys.exit(f"{thread_id!r} has no spans in ClickHouse — wrong project? not ingested yet?")

    rule(f"conversation {thread_id} — {len(trace_ids)} turn(s)")
    first_root: dict = {}
    for i, tid in enumerate(trace_ids, start=1):
        spans = reader.read_spans(project_id, tid)
        root = root_span(spans)
        first_root = first_root or root
        print(f"  turn {i}: {tid}  {len(spans)} spans  agent_id={root.get('agent_id')!r} "
              f"env={root.get('env')!r}  types={sorted({s.get('type') for s in spans})}")

    describe_specs(specs, first_root, trace_ids[0])
    install_taps(args.full, args.break_on_llm)

    svc = EvaluationService()
    if args.dry_run:
        # ponytail: stub the two write seams instead of threading a flag through the service.
        svc.score_writer = type(
            "DryRunWriter", (), {"write_eval_scores": lambda self, *a, **k: print(
                f"  (dry-run) NOT writing {len(a[3])} score row(s) to ClickHouse")}
        )()
        svc._cluster_failure = lambda *a, **k: print("  (dry-run) NOT clustering the failure")

    rule("running — every `result` frame below is what the SSE endpoint streams into the grid")

    def on_result(score: dict) -> None:
        print(f"\n  ▸ SCORE {score['name']} [{score['evaluation_level']}] "
              f"verdict={score['verdict'] or '(none)'} value={score['value']} "
              f"span={score['observation_id'] or '-'} trace={score['trace_id'] or '-'}")
        if score.get("string_value"):
            block("string_value", score["string_value"], args.full)
        if score.get("comment"):
            print(f"    comment: {score['comment'][:400]}")

    if args.break_before:
        print("  --break-before: pdb — `s` to step into the service")
        breakpoint()

    if args.trace_id:
        out = svc.evaluate_trace(project_id, args.trace_id, specs=specs, on_result=on_result,
                                 skip_conversation=True)
    else:
        out = svc.evaluate_thread(project_id, thread_id, specs=specs, on_result=on_result)

    rule(f"done — {json.dumps(out)}")
    if args.dry_run:
        print("(dry-run: nothing was persisted — the grid is unchanged)")


if __name__ == "__main__":
    main()
