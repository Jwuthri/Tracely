"use client";

import clsx from "clsx";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  activeAt, currentByActor, fmtMs, kindStyle, onStage, orderActors, toPlayEvents,
  type PlayEvent, type ReplayActor, type ReplayEvent,
} from "./timeline";

/* The conversation, acted out: one character per agent, sub-agents pulled in under the agent
   that spawned them, every tool/llm call a beat on a shared clock you can scrub. */

const SPEEDS = [0.5, 1, 2, 4];

export function ConversationStage({ threadId }: { threadId: string }) {
  const [data, setData] = useState<{ actors: ReplayActor[]; events: ReplayEvent[] } | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const raf = useRef<number | null>(null);
  const last = useRef<number>(0);

  useEffect(() => {
    let alive = true;
    fetch(`/api/session-replay?thread=${encodeURIComponent(threadId)}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => alive && setData({ actors: d.actors ?? [], events: d.events ?? [] }))
      .catch(() => alive && setData({ actors: [], events: [] }));
    return () => { alive = false; };
  }, [threadId]);

  const { events, total } = useMemo(
    () => toPlayEvents(data?.events ?? []),
    [data],
  );
  const actors = useMemo(() => orderActors(data?.actors ?? []), [data]);

  useEffect(() => {
    if (!playing || !total) return;
    const tick = (now: number) => {
      const dt = last.current ? now - last.current : 16;
      last.current = now;
      setT((prev) => {
        const next = prev + dt * speed;
        if (next >= total) { setPlaying(false); return total; }
        return next;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      last.current = 0;
    };
  }, [playing, speed, total]);

  const live = activeAt(events, t);
  const logRef = useRef<HTMLDivElement>(null);
  const current = currentByActor(events, t);
  const liveIds = new Set(live.map((e) => e.span_id));
  const played = events.filter((e) => e.pt <= t);

  if (!data) return <div className="card grid h-[420px] place-items-center font-mono text-[12px] text-fg-muted">loading the conversation…</div>;
  if (!events.length) {
    return (
      <div className="card grid h-[320px] place-items-center text-center">
        <div>
          <p className="text-[15px] font-semibold">Nothing to replay</p>
          <p className="mt-1 text-[13px] text-fg-muted">This conversation has no spans yet.</p>
        </div>
      </div>
    );
  }

  const restart = () => { setT(0); setPlaying(true); };

  return (
    <div className="space-y-4">
      {/* ── controls ── */}
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => (t >= total ? restart() : setPlaying((p) => !p))} className="btn-primary !py-1.5">
          {t >= total ? "↺ replay" : playing ? "❚❚ pause" : "▶ play"}
        </button>
        <button onClick={restart} className="btn-ghost">↺ restart</button>
        <div className="flex gap-1">
          {SPEEDS.map((s) => (
            <button key={s} onClick={() => setSpeed(s)}
              className={clsx("rounded-md border px-2 py-1 font-mono text-[11px] transition-colors",
                speed === s ? "border-signal/40 bg-signal/15 text-signal" : "border-line text-fg-muted hover:text-fg")}>
              {s}×
            </button>
          ))}
        </div>
        <span className="ml-auto font-mono text-[11px] text-fg-faint">
          {fmtMs(t)} / {fmtMs(total)} · {played.length}/{events.length} steps
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        {/* ── stage ── */}
        <div className="card relative overflow-hidden p-5">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_0%,rgba(34,211,238,0.06),transparent_60%)]" />
          <div className="relative space-y-3">
            {actors.map((a) => {
              const here = onStage(a, events, t);
              const doing = current[a.id];
              const busy = live.some((e) => e.actor === a.id);
              const failed = played.some((e) => e.actor === a.id && e.status === "error");
              return (
                <div key={a.id}
                  className={clsx("flex items-center gap-3 rounded-xl border p-3 transition-all duration-500",
                    a.depth > 0 && "ml-10",
                    here ? "border-line-bright bg-ink-800/80 opacity-100" : "border-line-soft bg-ink-900/40 opacity-35",
                    busy && "shadow-glow",
                    failed && here && "border-fail/50")}>
                  <Character actor={a} busy={busy} here={here} failed={failed} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[14px] font-semibold">{a.name}</span>
                      {a.kind === "subagent" && (
                        <span className="rounded border border-t_think/40 bg-t_think/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-t_think">
                          sub-agent
                        </span>
                      )}
                      {busy && <span className="font-mono text-[10px] text-ok">● working</span>}
                    </div>
                    <div className="mt-1 h-[22px]">
                      {here && doing ? (
                        <span key={doing.span_id}
                          className={clsx("stage-pop inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px]",
                            doing.status === "error" ? "border-fail/50 bg-fail-dim/50 text-fail" : "border-line bg-ink-700 text-fg")}
                          style={doing.status === "ok" ? { borderColor: `${kindStyle(doing.kind).color}55` } : undefined}>
                          <span style={{ color: kindStyle(doing.kind).color }}>{kindStyle(doing.kind).icon}</span>
                          {doing.name}
                          {doing.model && <span className="text-fg-faint">· {doing.model}</span>}
                          {liveIds.has(doing.span_id) && <span className="stage-dots" />}
                        </span>
                      ) : (
                        <span className="font-mono text-[11px] text-fg-faint">{here ? "…" : "not in this conversation yet"}</span>
                      )}
                    </div>
                  </div>
                  <div className="shrink-0 text-right font-mono text-[10px] text-fg-faint">
                    <div>{a.events} steps</div>
                    {a.errors > 0 && <div className="text-fail">{a.errors} failed</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── step log, synced to the playhead ── */}
        <aside className="card flex max-h-[520px] flex-col overflow-hidden">
          <div className="border-b border-line px-4 py-2.5 font-mono text-[11px] uppercase tracking-wider text-fg-muted">
            steps
          </div>
          <div ref={logRef} className="flex-1 space-y-0.5 overflow-y-auto p-2">
            {events.map((e) => {
              const done = e.pt <= t;
              const isLive = liveIds.has(e.span_id);
              const st = kindStyle(e.kind);
              return (
                <button key={`${e.trace_id}:${e.span_id}`}
                  ref={isLive ? (el) => el?.scrollIntoView({ block: "nearest" }) : undefined}
                  onClick={() => { setT(e.pt); setPlaying(false); }}
                  className={clsx("flex w-full items-center gap-2 rounded-md px-2 py-1 text-left transition-all",
                    done ? "opacity-100" : "opacity-30",
                    isLive && "bg-signal/10 ring-1 ring-signal/30",
                    e.status === "error" && done && "bg-fail-dim/40")}>
                  <span className="w-[34px] shrink-0 text-right font-mono text-[9px] text-fg-faint">{fmtMs(e.t_ms)}</span>
                  <span style={{ color: st.color }} className="shrink-0 text-[11px]">{st.icon}</span>
                  <span className="min-w-0 flex-1 truncate font-mono text-[11px]">{e.name}</span>
                  {e.status === "error" && <span className="font-mono text-[9px] text-fail">FAIL</span>}
                </button>
              );
            })}
          </div>
        </aside>
      </div>

      {/* ── lanes + scrubber ── */}
      <Lanes actors={actors} events={events} total={total} t={t} onSeek={(v) => { setT(v); setPlaying(false); }} />

      <p className="text-[12px] text-fg-muted">
        Long pauses between turns are squeezed so the replay stays watchable — the timestamps in the
        step list are the real ones. <Link href={`/sessions/${encodeURIComponent(threadId)}`} className="text-signal hover:underline">Open the full conversation →</Link>
      </p>
    </div>
  );
}

function Lanes({ actors, events, total, t, onSeek }: {
  actors: ReplayActor[]; events: PlayEvent[]; total: number; t: number; onSeek: (v: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const seek = (clientX: number) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * total);
  };
  return (
    <div className="card p-4">
      <div className="space-y-1.5">
        {actors.map((a) => (
          <div key={a.id} className="flex items-center gap-3">
            <span className={clsx("w-[120px] shrink-0 truncate font-mono text-[10px]", a.depth ? "pl-3 text-fg-faint" : "text-fg-muted")}
              title={a.name}>
              {a.depth ? "└ " : ""}{a.name}
            </span>
            <div className="relative h-5 flex-1 rounded bg-ink-800">
              {events.filter((e) => e.actor === a.id).map((e) => {
                const st = kindStyle(e.kind);
                return (
                  <span key={e.span_id}
                    onClick={() => onSeek(e.pt)}
                    title={`${e.name} · ${fmtMs(e.dur_ms)}`}
                    className="absolute top-1 h-3 cursor-pointer rounded-[2px] transition-opacity hover:opacity-100"
                    style={{
                      left: `${(e.pt / total) * 100}%`,
                      width: `${Math.max(0.6, (e.pdur / total) * 100)}%`,
                      background: e.status === "error" ? "#fb7185" : st.color,
                      opacity: e.pt <= t ? 0.95 : 0.28,
                    }} />
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div ref={ref} onMouseDown={(e) => seek(e.clientX)} className="relative mt-3 ml-[132px] h-6 cursor-pointer">
        <div className="absolute inset-x-0 top-2.5 h-1 rounded bg-ink-700" />
        <div className="absolute top-2.5 h-1 rounded bg-signal/60" style={{ width: `${(t / total) * 100}%` }} />
        <div className="absolute top-0 h-6 w-[2px] bg-signal shadow-glow" style={{ left: `${(t / total) * 100}%` }} />
      </div>
    </div>
  );
}

/** A tiny pixel character; hue is derived from the actor id so it's stable per agent. */
function Character({ actor, busy, here, failed }: { actor: ReplayActor; busy: boolean; here: boolean; failed: boolean }) {
  let h = 0;
  for (let i = 0; i < actor.id.length; i++) h = (h * 31 + actor.id.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  const size = actor.depth ? 34 : 42;
  return (
    <div className={clsx("relative shrink-0 transition-transform duration-300", busy && "stage-bob")}
      style={{ width: size, height: size }}>
      <svg viewBox="0 0 36 39" width={size} height={size} className={clsx(!here && "grayscale")}>
        <rect x="9" y="0" width="18" height="9" rx="3" fill={`hsl(${(hue + 140) % 360} 45% 30%)`} />
        <rect x="9" y="7" width="18" height="12" rx="2" fill="hsl(28 55% 74%)" />
        <rect x="13" y="11" width="3" height="3" fill="#1a2030" />
        <rect x="21" y="11" width="3" height="3" fill="#1a2030" />
        <rect x="15" y="16" width="7" height="2" rx="1" fill="#1a2030" opacity="0.6" />
        <rect x="6" y="19" width="24" height="14" rx="4" fill={`hsl(${hue} 62% 52%)`} />
        <rect x="12" y="33" width="5" height="6" fill="#222a3a" />
        <rect x="20" y="33" width="5" height="6" fill="#222a3a" />
      </svg>
      {busy && <span className="absolute -right-1 -top-1 h-3 w-3 animate-ping rounded-full bg-ok/70" />}
      {failed && <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-fail text-[9px] font-bold text-ink-900">!</span>}
    </div>
  );
}
