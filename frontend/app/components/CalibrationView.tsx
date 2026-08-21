"use client";

import clsx from "clsx";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TraceDetailData } from "@/app/lib/api";
import { judgeTakeaway } from "@/app/lib/calibration";
import { IO } from "./IO";
import { Meter } from "./Meter";
import { TimeAgo } from "./TimeAgo";
import { Badge, verdictVariant } from "./ui";

type Evaluator = {
  name: string;
  kind: string;
  level: string;
  total: number;
  fails: number;
  labeled: number;
  agree: number;
  agreement: number;
  false_pass: number;
  false_fail: number;
};

type QueueRow = {
  trace_id: string;
  observation_id: string;
  session_id: string;
  evaluation_level: string;
  verdict: string;
  value: number | null;
  comment: string;
  created_at: string;
  human_verdict: string | null;
  note: string | null;
};

const pct = (x: number) => `${Math.round(x * 100)}%`;

// One screen of verdicts at a time. Labeling is a one-at-a-time activity, and an evaluator with a
// few hundred graded runs used to render every one of them (each with its rationale comment) into
// the DOM the moment you selected it.
const QUEUE_PAGE = 25;

// Labels needed before an agreement % means anything. The denominator used to be the evaluator's
// whole verdict count ("0 / 1626"), which reads as an impossible chore — nobody hand-grades 1626
// runs, and nobody has to: a few dozen random draws pin the judge's accuracy down well enough to
// decide whether to let it block a merge.
// ponytail: a flat target, not a confidence-interval stopping rule. Wilson bounds if anyone asks.
const TARGET = 50;

export function CalibrationView() {
  const [evaluators, setEvaluators] = useState<Evaluator[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<"" | "FAIL" | "PASS">("");
  const [queue, setQueue] = useState<QueueRow[]>([]);
  const [i, setI] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [queueLoading, setQueueLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [revealed, setRevealed] = useState(false);

  const loadSummary = async () => {
    const r = await fetch("/api/calibration", { cache: "no-store" });
    const data: Evaluator[] = r.ok ? await r.json() : [];
    setEvaluators(data);
    return data;
  };

  useEffect(() => {
    loadSummary()
      .then((data) => {
        // Land on something worth calibrating: a judge, not a deterministic check.
        const first = data.find((e) => e.kind === "llm_judge") ?? data[0];
        setSelected((s) => s ?? first?.name ?? null);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) return;
    let live = true;
    setQueueLoading(true);
    setQueue([]); // drop the previous evaluator's rows rather than showing them under a new header
    fetch(
      `/api/calibration/${encodeURIComponent(selected)}/queue?limit=${QUEUE_PAGE}&verdict=${filter}`,
      { cache: "no-store" },
    )
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: QueueRow[]) => {
        if (!live) return;
        setQueue(rows);
        setHasMore(rows.length === QUEUE_PAGE);
        // Resume where the reviewer left off. All labeled → one past the end, i.e. the summary:
        // reopening at row 1 with the buttons still lit reads as "you have work left" when you
        // don't, and re-labeling what you already labeled tells you nothing new.
        const next = rows.findIndex((r) => !r.human_verdict);
        setI(next === -1 ? rows.length : next);
        setRevealed(false);
      })
      .finally(() => live && setQueueLoading(false));
    return () => {
      live = false;
    };
  }, [selected, filter]);

  const loadMore = useCallback(async () => {
    if (!selected) return;
    setMore(true);
    try {
      const r = await fetch(
        `/api/calibration/${encodeURIComponent(selected)}/queue?limit=${QUEUE_PAGE}&offset=${queue.length}&verdict=${filter}`,
        { cache: "no-store" },
      );
      const rows: QueueRow[] = r.ok ? await r.json() : [];
      setQueue((q) => [...q, ...rows]);
      setHasMore(rows.length === QUEUE_PAGE);
      return rows.length;
    } finally {
      setMore(false);
    }
  }, [selected, queue.length, filter]);

  const row = queue[i];

  const go = useCallback(
    (delta: number) => {
      setRevealed(false);
      setI((n) => {
        const next = n + delta;
        if (next < 0) return 0;
        if (next >= queue.length) {
          if (hasMore) void loadMore();
          return Math.min(next, queue.length); // one past the end = the "done" panel
        }
        return next;
      });
    },
    [queue.length, hasMore, loadMore],
  );

  const label = useCallback(
    async (human: string | null) => {
      if (!selected || !row) return;
      const target = row;
      const body = {
        score_name: selected,
        human_verdict: human ?? "",
        evaluation_level: target.evaluation_level,
        trace_id: target.trace_id,
        session_id: target.session_id,
        observation_id: target.observation_id,
        judge_verdict: target.verdict,
      };
      setQueue((q) => q.map((r) => (r === target ? { ...r, human_verdict: human } : r)));
      setRevealed(true);
      await fetch("/api/annotations", {
        method: human ? "POST" : "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).catch(() => {});
      loadSummary(); // refresh agreement cards
      if (human) setTimeout(() => go(1), 450); // let the reveal land, then advance
    },
    [selected, row, go],
  );

  // Labeling is a keyboard activity — reaching for the mouse on every one of fifty runs is the
  // difference between calibrating a judge and abandoning it halfway.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      const k = e.key.toLowerCase();
      if (k === "p") void label("PASS");
      else if (k === "f") void label("FAIL");
      else if (k === "s" || e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (k === "r") setRevealed(true);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [label, go]);

  const sel = evaluators.find((e) => e.name === selected);
  const judges = evaluators.filter((e) => e.kind === "llm_judge");
  const structural = evaluators.filter((e) => e.kind !== "llm_judge");

  if (loading) return <div className="font-mono text-[12px] text-fg-faint">loading…</div>;
  if (!evaluators.length)
    return (
      <div className="card p-6 text-[13px] text-fg-muted">
        No evaluator verdicts yet. Run some traces with evaluators enabled, then come back to
        calibrate them. LLM judges only run once your workspace has an OpenRouter key
        (<a href="/settings/llm" className="text-signal hover:underline">Settings → LLM key</a>) —
        without one, only the structural evaluators produce verdicts.
      </div>
    );

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      {/* evaluator list — judges first, deterministic checks below */}
      <div className="space-y-2">
        {judges.map((e) => (
          <EvaluatorCard key={e.name} e={e} selected={e.name === selected} onSelect={setSelected} />
        ))}
        {structural.length > 0 && (
          <div className="pt-2">
            <div className="px-1 pb-2 font-mono text-[9.5px] uppercase tracking-[0.18em] text-fg-faint">
              Deterministic · calibration optional
            </div>
            {structural.map((e) => (
              <EvaluatorCard
                key={e.name}
                e={e}
                selected={e.name === selected}
                onSelect={setSelected}
                muted
              />
            ))}
          </div>
        )}
      </div>

      {/* one verdict at a time, with the evidence that produced it */}
      <div className="space-y-3">
        {sel && sel.kind !== "llm_judge" && (
          <div className="rounded-xl border border-warn/25 bg-warn/[0.05] px-5 py-3 text-[12.5px] leading-relaxed text-fg-muted">
            <span className="font-medium text-warn">Deterministic check.</span>{" "}
            <span className="font-mono text-[12px]">{sel.name}</span> is code, not a rubric — it
            reads the run’s own numbers (errors, latency, tool results), so there is no judgement to
            disagree with. Spot-check it if you like; calibration is for LLM judges.
            {!judges.length && (
              <>
                {" "}
                This workspace has none yet — they need an{" "}
                <a href="/settings/llm" className="text-signal hover:underline">
                  OpenRouter key
                </a>
                .
              </>
            )}
          </div>
        )}
        {sel && (
          <div className="rounded-xl border border-line bg-ink-900/40 px-5 py-3.5">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <Stat label="Agreement" value={sel.labeled ? pct(sel.agreement) : "—"} />
              <Stat label="Reviewed" value={`${sel.labeled} / ${Math.min(TARGET, sel.total)}`} hint={`${sel.total} verdicts recorded — a sample of ${TARGET} is enough to judge the judge`} />
              <Stat label="Missed fails" value={sel.false_pass} tone={sel.false_pass ? "fail" : undefined} hint="judge PASS, you FAIL — the gate would let this through" />
              <Stat label="Over-flags" value={sel.false_fail} tone={sel.false_fail ? "warn" : undefined} hint="judge FAIL, you PASS — the gate would block a good PR" />
              <div className="ml-auto flex items-center gap-1">
                {([["", "All"], ["FAIL", "Fails"], ["PASS", "Passes"]] as const).map(([v, l]) => (
                  <button
                    key={v}
                    onClick={() => setFilter(v)}
                    className={clsx(
                      "rounded-lg border px-2.5 py-1 font-mono text-[11px] transition-colors",
                      filter === v
                        ? "border-signal/40 bg-signal/[0.08] text-fg"
                        : "border-line text-fg-muted hover:text-fg",
                    )}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
            <Meter
              className="mt-3"
              segments={25}
              value={(sel.labeled / Math.min(TARGET, sel.total || TARGET)) * 100}
            />
            <Takeaway e={sel} />
          </div>
        )}

        {queueLoading ? (
          <div className="font-mono text-[12px] text-fg-faint">loading queue…</div>
        ) : !queue.length ? (
          <div className="card p-6 text-[13px] text-fg-muted">
            No {filter ? `${filter.toLowerCase()} ` : ""}verdicts to review for this evaluator.
          </div>
        ) : !row ? (
          <div className="card space-y-4 p-6">
            <p className="text-[13px] text-fg-muted">
              Sample reviewed — {sel?.labeled ?? 0} verdict{sel?.labeled === 1 ? "" : "s"} labeled.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setI(0)}
                className="rounded-lg border border-line bg-ink-800 px-4 py-2 text-[12.5px] font-medium text-fg-muted transition-colors hover:text-fg"
              >
                Look at them again
              </button>
              {hasMore && (
                <button
                  onClick={() => loadMore().then(() => setI(queue.length))}
                  disabled={more}
                  className="rounded-lg border border-line bg-ink-800 px-4 py-2 text-[12.5px] font-medium text-fg-muted transition-colors hover:text-fg disabled:opacity-50"
                >
                  {more ? "Loading…" : "Draw another 25"}
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            <ReviewCard
              key={`${row.trace_id}:${row.observation_id}:${i}`}
              row={row}
              revealed={revealed || !!row.human_verdict || sel?.kind !== "llm_judge"}
              onReveal={() => setRevealed(true)}
              onLabel={label}
            />
            <div className="flex items-center justify-between gap-3 px-1">
              <button
                onClick={() => go(-1)}
                disabled={i === 0}
                className="font-mono text-[11px] text-fg-faint transition-colors hover:text-fg disabled:opacity-30"
              >
                ← prev
              </button>
              <span className="font-mono text-[10.5px] text-fg-faint">
                {i + 1} of {queue.length}
                {hasMore ? "+" : ""} sampled · <Kbd>p</Kbd> pass ·{" "}
                <Kbd>f</Kbd> fail · <Kbd>s</Kbd> skip
              </span>
              <button
                onClick={() => go(1)}
                className="font-mono text-[11px] text-fg-faint transition-colors hover:text-fg"
              >
                skip →
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// The number is not the answer — "0%" is only useful once it says which way the judge is wrong and
// what to do about it.
function Takeaway({ e }: { e: Evaluator }) {
  const t = judgeTakeaway(e);
  if (!t) return null;
  return (
    <p
      className={clsx(
        "mt-3 text-[12.5px] leading-relaxed",
        t.tone === "ok" ? "text-ok" : t.tone === "warn" ? "text-warn" : "text-fail",
      )}
    >
      {t.text}
    </p>
  );
}

function EvaluatorCard({
  e,
  selected,
  onSelect,
  muted,
}: {
  e: Evaluator;
  selected: boolean;
  onSelect: (n: string) => void;
  muted?: boolean;
}) {
  const goal = Math.min(TARGET, e.total);
  return (
    <button
      onClick={() => onSelect(e.name)}
      className={clsx(
        "mb-2 w-full rounded-xl border p-4 text-left transition-colors",
        selected
          ? "border-signal/40 bg-signal/[0.06]"
          : "border-line bg-ink-900/40 hover:border-line-strong hover:bg-hilite/[0.02]",
        muted && !selected && "opacity-60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[12.5px] text-fg">{e.name}</span>
        <span
          className={clsx(
            "shrink-0 font-display text-[18px] font-bold tabular-nums",
            e.labeled === 0 ? "text-fg-faint" : e.agreement >= 0.8 ? "text-ok" : e.agreement >= 0.5 ? "text-warn" : "text-fail",
          )}
        >
          {e.labeled ? pct(e.agreement) : "—"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-fg-faint">
        <span>{e.labeled}/{goal} reviewed</span>
        {e.false_pass > 0 && <span className="text-fail">{e.false_pass} missed</span>}
        {e.false_fail > 0 && <span className="text-warn">{e.false_fail} over-flag</span>}
      </div>
    </button>
  );
}

// The judged target's own input/output. Without it the reviewer is being asked to second-guess a
// verdict from a truncated trace id — the one thing on screen that carries no information at all.
function Evidence({ row }: { row: QueueRow }) {
  const [data, setData] = useState<TraceDetailData | null>(null);
  const [err, setErr] = useState(false);
  const id = row.trace_id || row.session_id;
  const seen = useRef("");

  useEffect(() => {
    if (!id || seen.current === id) return;
    seen.current = id;
    setData(null);
    setErr(false);
    fetch(`/api/trace?id=${encodeURIComponent(id)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setData)
      .catch(() => setErr(true));
  }, [id]);

  // Span-level scores judged one span, so show that span. A run/conversation-level score judged the
  // whole run, whose input and output are its boundaries — the first span that received something
  // and the last one that produced something. Picking "the root span" instead showed (empty) on
  // every SDK that wraps the run in a bare parent span (most of them).
  const picked = useMemo(() => {
    const spans = data?.spans ?? []; // reader order = start_time
    if (!spans.length) return null;
    if (row.observation_id) {
      const s = spans.find((x) => x.span_id === row.observation_id);
      return s ? { name: `${s.type} · ${s.name}`, input: s.input, output: s.output } : null;
    }
    const inSpan = spans.find((s) => s.input);
    const outSpan = [...spans].reverse().find((s) => s.output);
    return {
      name: `${spans.length} span${spans.length === 1 ? "" : "s"}`,
      input: inSpan?.input ?? null,
      output: outSpan?.output ?? null,
    };
  }, [data, row.observation_id]);

  if (err) return <p className="font-mono text-[11px] text-fg-faint">could not load the trace</p>;
  if (!data) return <p className="font-mono text-[11px] text-fg-faint">loading evidence…</p>;
  if (!picked)
    return <p className="font-mono text-[11px] text-fg-faint">no matching span in this trace</p>;
  // Two "(empty)" boxes read as a rendering bug. Plenty of runs carry no I/O at all (a bare
  // wrapper span, an SDK smoke test) — say that, so the reviewer skips instead of squinting.
  if (!picked.input && !picked.output)
    return (
      <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[12.5px] text-fg-faint">
        This run recorded no input or output — nothing here to grade. Open the trace to see what
        actually ran, or skip it.
      </div>
    );

  return (
    <div className="space-y-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">{picked.name}</div>
      <Panel title="Input">
        <IO value={picked.input} />
      </Panel>
      <Panel title="Output">
        <IO value={picked.output} />
      </Panel>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-ink-900/40">
      <div className="border-b border-line px-4 py-1.5 font-mono text-[9.5px] uppercase tracking-[0.18em] text-fg-faint">
        {title}
      </div>
      {children}
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-ink-800 px-1 py-px font-mono text-[9.5px] text-fg-faint">
      {children}
    </kbd>
  );
}

function ReviewCard({
  row,
  revealed,
  onReveal,
  onLabel,
}: {
  row: QueueRow;
  revealed: boolean;
  onReveal: () => void;
  onLabel: (v: string | null) => void;
}) {
  const human = row.human_verdict?.toUpperCase() ?? null;
  const agreed = human && human === row.verdict.toUpperCase();
  const href = `/traces/${row.trace_id || row.session_id}`;
  return (
    <div className="card space-y-4 p-5">
      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-fg-faint">
        <span>{row.evaluation_level}</span>
        <span>·</span>
        <TimeAgo ts={row.created_at} />
        {row.value !== null && (
          <>
            <span>·</span>
            <span className="tabular-nums">value {row.value}</span>
          </>
        )}
        <a href={href} className="ml-auto normal-case text-signal hover:underline">
          open trace ↗
        </a>
      </div>

      <Evidence row={row} />

      {/* Your call first, the judge's second — an agreement % measured against an anchored reviewer
          measures the anchor, not the judge. Sticky, because the evidence is as tall as the run:
          a chat input plus a tool-calling output pushed the two buttons a full screen below the
          fold, so every single item cost a scroll down to answer and a scroll back up to read. */}
      <div className="sticky bottom-0 -mx-5 -mb-5 rounded-b-xl border-t border-line bg-ink-800/95 px-5 py-4 backdrop-blur">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-fg-faint">
            Your verdict
          </span>
          <VerdictButton active={human === "PASS"} tone="ok" onClick={() => onLabel(human === "PASS" ? null : "PASS")}>
            pass <Kbd>p</Kbd>
          </VerdictButton>
          <VerdictButton active={human === "FAIL"} tone="fail" onClick={() => onLabel(human === "FAIL" ? null : "FAIL")}>
            fail <Kbd>f</Kbd>
          </VerdictButton>
          {!revealed && (
            <button
              onClick={onReveal}
              className="ml-auto font-mono text-[10.5px] text-fg-faint underline decoration-dotted hover:text-fg"
            >
              show the judge’s verdict
            </button>
          )}
        </div>

        {revealed && (
          <div className="mt-3 space-y-2 rounded-lg border border-line bg-ink-900/40 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={verdictVariant(row.verdict)} dot>
                judge {row.verdict}
              </Badge>
              {human && (
                <span
                  className={clsx(
                    "font-mono text-[11px]",
                    agreed ? "text-ok" : row.verdict.toUpperCase() === "FAIL" ? "text-warn" : "text-fail",
                  )}
                >
                  {agreed
                    ? "you agree"
                    : row.verdict.toUpperCase() === "FAIL"
                      ? "over-flag — the gate would block this"
                      : "missed fail — the gate would let this through"}
                </span>
              )}
            </div>
            {row.comment ? (
              <p className="text-[12.5px] leading-relaxed text-fg-muted">{row.comment}</p>
            ) : (
              <p className="font-mono text-[11px] text-fg-faint">no rationale recorded</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, tone, hint }: { label: string; value: string | number; tone?: "fail" | "warn"; hint?: string }) {
  return (
    <div title={hint}>
      <div className="font-mono text-[9.5px] uppercase tracking-[0.18em] text-fg-faint">{label}</div>
      <div
        className={clsx(
          "mt-0.5 font-display text-[17px] font-bold tabular-nums",
          tone === "fail" ? "text-fail" : tone === "warn" ? "text-warn" : "text-fg",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function VerdictButton({
  active,
  tone,
  onClick,
  children,
}: {
  active: boolean;
  tone: "ok" | "fail";
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "flex items-center gap-2 rounded-lg border px-3.5 py-2 font-mono text-[12px] transition-colors",
        active && tone === "ok" && "border-ok/50 bg-ok/15 text-ok",
        active && tone === "fail" && "border-fail/50 bg-fail/15 text-fail",
        !active && "border-line text-fg-muted hover:border-line-strong hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}
