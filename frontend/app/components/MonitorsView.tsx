"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";
import { Badge } from "./ui";

// ── types ────────────────────────────────────────────────────────────────────
type ConditionType = "fail_rate_over" | "score_below" | "trace_failure_rate";
type ChannelType = "slack" | "webhook";

type Channel = { type: ChannelType; url: string; headers?: Record<string, string> };
type Condition = {
  type: ConditionType;
  score_name?: string;
  window_minutes: number;
  min_samples: number;
  threshold: number;
};

type Monitor = {
  id: string;
  name: string;
  description: string;
  target_agent: string;
  condition: Condition;
  channels: Channel[];
  enabled: boolean;
  min_interval_seconds: number;
  last_evaluated_at: string | null;
  last_fired_at: string | null;
  last_fired_summary: string;
  created_at: string | null;
};

type TestResult = {
  fired: boolean;
  evaluated: boolean;
  skipped_reason?: string;
  sample_size: number;
  score: number | null;
  delivered?: { ok: number; fail: number; skipped: number };
};

// ── labels + helpers ─────────────────────────────────────────────────────────
const COND_LABEL: Record<ConditionType, string> = {
  fail_rate_over: "FAIL rate over threshold",
  score_below: "Avg score drops below threshold",
  trace_failure_rate: "Trace failure rate over threshold",
};

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
function ago(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.round(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return RELATIVE.format(-m, "minute");
  const h = Math.round(m / 60);
  if (h < 24) return RELATIVE.format(-h, "hour");
  return RELATIVE.format(-Math.round(h / 24), "day");
}

function pctOrDash(x: number | null): string {
  return x == null ? "—" : `${Math.round(x * 100)}%`;
}

// ── view ─────────────────────────────────────────────────────────────────────
export function MonitorsView() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [error, setError] = useState("");

  const reload = async () => {
    setError("");
    const r = await fetch("/api/monitors", { cache: "no-store" });
    if (!r.ok) {
      setError(`failed to load monitors (${r.status})`);
      return;
    }
    setMonitors(await r.json());
  };

  useEffect(() => {
    void reload().finally(() => setLoading(false));
  }, []);

  const onTest = async (m: Monitor) => {
    setTestResults((prev) => ({ ...prev, [m.id]: { ...(prev[m.id] || {}), evaluated: false, fired: false, sample_size: 0, score: null } }));
    const r = await fetch(`/api/monitors/${encodeURIComponent(m.id)}/test`, { method: "POST" });
    if (!r.ok) {
      setError(`test failed (${r.status})`);
      return;
    }
    const res: TestResult = await r.json();
    setTestResults((prev) => ({ ...prev, [m.id]: res }));
    void reload(); // refresh last_evaluated_at / last_fired_*
  };

  const onDelete = async (m: Monitor) => {
    if (!confirm(`Delete monitor "${m.name}"?`)) return;
    const r = await fetch(`/api/monitors/${encodeURIComponent(m.id)}`, { method: "DELETE" });
    if (!r.ok) {
      setError(`delete failed (${r.status})`);
      return;
    }
    await reload();
  };

  const onToggle = async (m: Monitor) => {
    const r = await fetch(`/api/monitors/${encodeURIComponent(m.id)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled: !m.enabled }),
    });
    if (!r.ok) {
      setError(`toggle failed (${r.status})`);
      return;
    }
    await reload();
  };

  if (loading) return <div className="text-fg-muted">Loading monitors…</div>;

  return (
    <div className="space-y-4">
      {error && (
        <div role="alert" className="rounded-md border border-fail/30 bg-fail/10 px-3 py-2 text-[12.5px] text-fail">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <div className="text-[12.5px] text-fg-muted">
          {monitors.length} monitor{monitors.length === 1 ? "" : "s"} ·{" "}
          {monitors.filter((m) => m.enabled).length} enabled
        </div>
        <button
          onClick={() => setShowCreate((x) => !x)}
          className="rounded-md border border-line bg-ink-900 px-3 py-1.5 text-[12.5px] text-fg hover:bg-white/[0.04]"
        >
          {showCreate ? "Cancel" : "+ New monitor"}
        </button>
      </div>

      {showCreate && (
        <CreateForm
          onCancel={() => setShowCreate(false)}
          onCreated={async () => {
            setShowCreate(false);
            await reload();
          }}
          onError={setError}
        />
      )}

      {monitors.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-3">
          {monitors.map((m) => (
            <MonitorCard
              key={m.id}
              monitor={m}
              testResult={testResults[m.id]}
              onTest={() => onTest(m)}
              onDelete={() => onDelete(m)}
              onToggle={() => onToggle(m)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── card ─────────────────────────────────────────────────────────────────────
function MonitorCard({
  monitor: m,
  testResult,
  onTest,
  onDelete,
  onToggle,
}: {
  monitor: Monitor;
  testResult?: TestResult;
  onTest: () => void;
  onDelete: () => void;
  onToggle: () => void;
}) {
  const fired = !!m.last_fired_at;
  return (
    <div className={clsx("card p-4", fired && "border-warn/30 bg-warn/[0.03]")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-display text-[16px] font-semibold text-fg">{m.name}</h3>
            <Badge variant={m.enabled ? "ok" : "neutral"}>{m.enabled ? "ENABLED" : "DISABLED"}</Badge>
            {fired && <Badge variant="warn">FIRED {ago(m.last_fired_at)}</Badge>}
          </div>
          {m.description && <p className="mt-1 text-[12.5px] text-fg-muted">{m.description}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-fg-faint">
            <span className="rounded bg-ink-900 px-2 py-0.5">{COND_LABEL[m.condition.type]}</span>
            {m.condition.score_name && (
              <span className="rounded bg-ink-900 px-2 py-0.5">{m.condition.score_name}</span>
            )}
            <span className="rounded bg-ink-900 px-2 py-0.5">
              threshold {m.condition.type === "score_below"
                ? `<${m.condition.threshold.toFixed(2)}`
                : `>${Math.round(m.condition.threshold * 100)}%`}
            </span>
            <span className="rounded bg-ink-900 px-2 py-0.5">
              window {m.condition.window_minutes}m
            </span>
            <span className="rounded bg-ink-900 px-2 py-0.5">
              min samples {m.condition.min_samples}
            </span>
            {m.target_agent && (
              <span className="rounded bg-signal/15 px-2 py-0.5 text-signal">agent: {m.target_agent}</span>
            )}
            {(m.channels || []).map((c, i) => (
              <span key={i} className="rounded bg-ink-900 px-2 py-0.5">
                {c.type === "slack" ? "💬 slack" : "🔗 webhook"}
              </span>
            ))}
          </div>
          {m.last_fired_summary && (
            <p className="mt-2 font-mono text-[11.5px] text-fg-muted">
              <span className="text-fg-faint">last:</span> {m.last_fired_summary}
            </p>
          )}
          {testResult && (
            <div className="mt-2 rounded-md border border-line bg-ink-900/60 px-3 py-2 text-[12px]">
              <span className={testResult.fired ? "text-warn" : "text-fg-muted"}>
                Test result · {testResult.fired ? "WOULD FIRE" : "quiet"}
              </span>
              <span className="ml-3 font-mono text-fg-faint">
                {testResult.sample_size} samples · {testResult.evaluated ? "score" : "skipped"}{" "}
                {testResult.score == null ? "—" : pctOrDash(testResult.score)}
                {testResult.skipped_reason ? ` (${testResult.skipped_reason})` : ""}
              </span>
              {testResult.delivered && (
                <span className="ml-3 font-mono text-fg-faint">
                  alerts → ok:{testResult.delivered.ok} fail:{testResult.delivered.fail} skipped:{testResult.delivered.skipped}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col gap-2">
          <button
            onClick={onTest}
            className="rounded-md border border-line bg-ink-900 px-3 py-1 text-[12px] text-fg hover:bg-white/[0.04]"
          >
            Test now
          </button>
          <button
            onClick={onToggle}
            className="rounded-md border border-line bg-ink-900 px-3 py-1 text-[12px] text-fg-muted hover:text-fg"
          >
            {m.enabled ? "Disable" : "Enable"}
          </button>
          <button
            onClick={onDelete}
            className="rounded-md border border-line bg-ink-900 px-3 py-1 text-[12px] text-fail/80 hover:text-fail"
          >
            Delete
          </button>
        </div>
      </div>
      <div className="mt-2 font-mono text-[10.5px] text-fg-faint">
        last evaluated {ago(m.last_evaluated_at)} · dedup {Math.round(m.min_interval_seconds / 60)}m
      </div>
    </div>
  );
}

// ── create form ──────────────────────────────────────────────────────────────
function CreateForm({
  onCreated,
  onCancel,
  onError,
}: {
  onCreated: () => void;
  onCancel: () => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [targetAgent, setTargetAgent] = useState("");
  const [condType, setCondType] = useState<ConditionType>("fail_rate_over");
  const [scoreName, setScoreName] = useState("tracely.run.quality");
  const [windowMin, setWindowMin] = useState(60);
  const [minSamples, setMinSamples] = useState(20);
  const [threshold, setThreshold] = useState(0.2);
  const [channelType, setChannelType] = useState<ChannelType>("slack");
  const [channelUrl, setChannelUrl] = useState("");
  const [minInterval, setMinInterval] = useState(900);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!name.trim()) return onError("name required");
    if (!channelUrl.trim()) return onError("channel URL required");
    setSubmitting(true);
    try {
      const condition: Condition = {
        type: condType,
        window_minutes: windowMin,
        min_samples: minSamples,
        threshold,
      };
      if (condType !== "trace_failure_rate") condition.score_name = scoreName;
      const r = await fetch("/api/monitors", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name, description, target_agent: targetAgent,
          condition,
          channels: [{ type: channelType, url: channelUrl }],
          min_interval_seconds: minInterval,
          enabled: true,
        }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as { detail?: string }));
        onError(body?.detail || `create failed (${r.status})`);
        return;
      }
      onCreated();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card space-y-3 p-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="quality fail-rate spike" />
        </Field>
        <Field label="Target agent (optional)">
          <Input value={targetAgent} onChange={(e) => setTargetAgent(e.target.value)} placeholder="planner — blank = all" />
        </Field>
        <Field label="Description (optional)" wide>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="alert when answer quality FAILs jump" />
        </Field>
        <Field label="Condition">
          <Select value={condType} onChange={(e) => setCondType(e.target.value as ConditionType)}>
            <option value="fail_rate_over">FAIL rate over threshold</option>
            <option value="score_below">Avg score drops below threshold</option>
            <option value="trace_failure_rate">Trace failure rate over threshold</option>
          </Select>
        </Field>
        {condType !== "trace_failure_rate" && (
          <Field label="Score name">
            <Input value={scoreName} onChange={(e) => setScoreName(e.target.value)} placeholder="tracely.run.quality" />
          </Field>
        )}
        <Field label="Window (minutes)">
          <Input
            type="number" min={1} max={10080} value={windowMin}
            onChange={(e) => setWindowMin(Number(e.target.value || 1))}
          />
        </Field>
        <Field label="Min samples">
          <Input
            type="number" min={1} max={10000} value={minSamples}
            onChange={(e) => setMinSamples(Number(e.target.value || 1))}
          />
        </Field>
        <Field label={condType === "score_below" ? "Threshold (numeric)" : "Threshold (rate 0–1)"}>
          <Input
            type="number" min={0} max={condType === "score_below" ? 999 : 1} step={0.01}
            value={threshold} onChange={(e) => setThreshold(Number(e.target.value || 0))}
          />
        </Field>
        <Field label="Dedup interval (seconds)">
          <Input
            type="number" min={0} max={86400} step={60} value={minInterval}
            onChange={(e) => setMinInterval(Number(e.target.value || 0))}
          />
        </Field>
        <Field label="Channel type">
          <Select value={channelType} onChange={(e) => setChannelType(e.target.value as ChannelType)}>
            <option value="slack">Slack incoming webhook</option>
            <option value="webhook">Generic webhook</option>
          </Select>
        </Field>
        <Field label="Channel URL" wide>
          <Input
            value={channelUrl} onChange={(e) => setChannelUrl(e.target.value)}
            placeholder={channelType === "slack" ? "https://hooks.slack.com/services/..." : "https://your-host/hook"}
          />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="rounded-md border border-line bg-ink-900 px-3 py-1.5 text-[12.5px] text-fg-muted hover:text-fg"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={submitting}
          className="rounded-md border border-signal/40 bg-signal/15 px-3 py-1.5 text-[12.5px] text-signal hover:bg-signal/25 disabled:opacity-60"
        >
          {submitting ? "Creating…" : "Create monitor"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={clsx("block", wide && "md:col-span-2")}>
      <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-fg-faint">{label}</div>
      {children}
    </label>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={clsx(
        "w-full rounded-md border border-line bg-ink-900 px-2.5 py-1.5 text-[13px] text-fg",
        "outline-none focus:border-signal/50",
        props.className,
      )}
    />
  );
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={clsx(
        "w-full rounded-md border border-line bg-ink-900 px-2.5 py-1.5 text-[13px] text-fg",
        "outline-none focus:border-signal/50",
        props.className,
      )}
    />
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-line bg-ink-900/40 px-6 py-12 text-center">
      <p className="text-fg-muted">No monitors yet.</p>
      <p className="mt-2 text-[12.5px] text-fg-faint">
        Create one with <span className="text-fg-muted">+ New monitor</span>, give it a Slack
        webhook, and it&apos;ll page you the next time a quality judge starts failing or the
        trace failure rate spikes.
      </p>
    </div>
  );
}
