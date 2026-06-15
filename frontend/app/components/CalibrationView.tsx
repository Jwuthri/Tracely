"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";
import { Badge, verdictVariant } from "./ui";

type Evaluator = {
  name: string;
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
const flip = (v: string) => (v.toUpperCase() === "FAIL" ? "PASS" : "FAIL");

export function CalibrationView() {
  const [evaluators, setEvaluators] = useState<Evaluator[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueueRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [queueLoading, setQueueLoading] = useState(false);

  const loadSummary = async () => {
    const r = await fetch("/api/calibration", { cache: "no-store" });
    const data: Evaluator[] = r.ok ? await r.json() : [];
    setEvaluators(data);
    return data;
  };

  useEffect(() => {
    loadSummary()
      .then((data) => setSelected((s) => s ?? data[0]?.name ?? null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setQueueLoading(true);
    fetch(`/api/calibration/${encodeURIComponent(selected)}/queue?limit=100`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then(setQueue)
      .finally(() => setQueueLoading(false));
  }, [selected]);

  async function label(row: QueueRow, human: string | null) {
    if (!selected) return;
    const body = {
      score_name: selected,
      human_verdict: human ?? "",
      evaluation_level: row.evaluation_level,
      trace_id: row.trace_id,
      session_id: row.session_id,
      observation_id: row.observation_id,
      judge_verdict: row.verdict,
    };
    // optimistic
    setQueue((q) => q.map((r) => (r === row ? { ...r, human_verdict: human } : r)));
    await fetch("/api/annotations", {
      method: human ? "POST" : "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => {});
    loadSummary(); // refresh agreement cards
  }

  const sel = evaluators.find((e) => e.name === selected);

  if (loading) return <div className="font-mono text-[12px] text-fg-faint">loading…</div>;
  if (!evaluators.length)
    return (
      <div className="card p-6 text-[13px] text-fg-muted">
        No evaluator verdicts yet. Run some traces with evaluators enabled, then come back to calibrate them.
      </div>
    );

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      {/* evaluator list */}
      <div className="space-y-2">
        {evaluators.map((e) => (
          <button
            key={e.name}
            onClick={() => setSelected(e.name)}
            className={clsx(
              "w-full rounded-xl border p-4 text-left transition-colors",
              e.name === selected
                ? "border-signal/40 bg-signal/[0.06]"
                : "border-line bg-ink-900/40 hover:border-line-strong hover:bg-white/[0.02]",
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
              <span>{e.labeled}/{e.total} labeled</span>
              {e.false_pass > 0 && <span className="text-fail">{e.false_pass} missed</span>}
              {e.false_fail > 0 && <span className="text-warn">{e.false_fail} over-flag</span>}
            </div>
          </button>
        ))}
      </div>

      {/* labeling queue for the selected evaluator */}
      <div className="space-y-3">
        {sel && (
          <div className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-ink-900/40 px-5 py-3.5">
            <Stat label="Agreement" value={sel.labeled ? pct(sel.agreement) : "—"} />
            <Stat label="Labeled" value={`${sel.labeled} / ${sel.total}`} />
            <Stat label="Missed fails" value={sel.false_pass} tone={sel.false_pass ? "fail" : undefined} hint="judge PASS, you FAIL" />
            <Stat label="Over-flags" value={sel.false_fail} tone={sel.false_fail ? "warn" : undefined} hint="judge FAIL, you PASS" />
          </div>
        )}

        {queueLoading ? (
          <div className="font-mono text-[12px] text-fg-faint">loading queue…</div>
        ) : (
          queue.map((row, i) => {
            const agreeActive = row.human_verdict?.toUpperCase() === row.verdict.toUpperCase();
            const disagreeActive = !!row.human_verdict && !agreeActive;
            const href = `/traces/${row.trace_id || row.session_id}`;
            return (
              <div key={`${row.trace_id}:${row.observation_id}:${i}`} className="card p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Badge variant={verdictVariant(row.verdict)} dot>
                        judge {row.verdict}
                      </Badge>
                      <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">
                        {row.evaluation_level}
                      </span>
                      <a href={href} className="font-mono text-[10.5px] text-signal hover:underline">
                        {(row.trace_id || row.session_id).slice(0, 12)}…
                      </a>
                    </div>
                    {row.comment && (
                      <p className="mt-2 line-clamp-3 text-[12.5px] leading-relaxed text-fg-muted">{row.comment}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <LabelButton
                      active={agreeActive}
                      tone="ok"
                      title="Agree with the judge"
                      onClick={() => label(row, agreeActive ? null : row.verdict)}
                    >
                      ✓ agree
                    </LabelButton>
                    <LabelButton
                      active={disagreeActive}
                      tone="fail"
                      title="Disagree with the judge"
                      onClick={() => label(row, disagreeActive ? null : flip(row.verdict))}
                    >
                      ✗ disagree
                    </LabelButton>
                  </div>
                </div>
              </div>
            );
          })
        )}
        {!queueLoading && !queue.length && (
          <div className="card p-6 text-[13px] text-fg-muted">No verdicts to review for this evaluator.</div>
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

function LabelButton({
  active,
  tone,
  title,
  onClick,
  children,
}: {
  active: boolean;
  tone: "ok" | "fail";
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className={clsx(
        "rounded-lg border px-2.5 py-1.5 font-mono text-[11px] transition-colors",
        active && tone === "ok" && "border-ok/50 bg-ok/15 text-ok",
        active && tone === "fail" && "border-fail/50 bg-fail/15 text-fail",
        !active && "border-line text-fg-muted hover:border-line-strong hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}
