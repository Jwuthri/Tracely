"use client";

import clsx from "clsx";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  EMPTY_LOCAL,
  EMPTY_STATUS,
  XP_PER_STEP,
  deriveDailies,
  deriveSteps,
  questRank,
  settleDaily,
  stepComplete,
  visitMarker,
  type QuestLocal,
  type QuestStatus,
} from "@/app/lib/quest";
import { THEME_KEY } from "@/app/components/ThemeToggle";

/* The gamified onboarding quest — a progress-ring launcher in the topbar opening a
   checklist that walks a new user through EVERY feature: API key → OpenRouter key → first trace
   → traces / evaluators / trends / replay / fleet / theme → failure → case → gate. On top of the
   one-time quest sit three DAILY challenges (rotated deterministically by date) that feed a
   lifetime score and a day streak. Counts come from /api/onboarding; page-visit steps tick via
   usePathname. Mounted once inside the Topbar — which the (app) layout renders once — so it
   survives navigation and sees every route. */

const STORE = "tracely_quest_v1";

const dayKey = () => new Date().toISOString().slice(0, 10); // UTC, matches the backend's buckets

function loadLocal(): QuestLocal {
  try {
    return { ...EMPTY_LOCAL, ...JSON.parse(localStorage.getItem(STORE) ?? "{}") };
  } catch {
    return { ...EMPTY_LOCAL };
  }
}

/** Deterministic scatter (no Math.random → no hydration drift, stable across renders). */
function Confetti() {
  const colors = ["#22d3ee", "#4ade80", "#fbbf24", "#f87171", "#a78bfa"];
  return (
    <div className="pointer-events-none fixed inset-0 z-50 overflow-hidden" aria-hidden>
      {Array.from({ length: 40 }).map((_, i) => (
        <span
          key={i}
          style={{
            position: "absolute",
            top: "-3vh",
            left: `${(i * 137) % 100}%`,
            width: 7,
            height: 11,
            background: colors[i % colors.length],
            borderRadius: 2,
            opacity: 0.95,
            transform: `rotate(${(i * 53) % 360}deg)`,
            animation: `quest-fall ${2.2 + (i % 5) * 0.35}s ease-in ${(i % 7) * 0.12}s forwards`,
          }}
        />
      ))}
      <style>{`@keyframes quest-fall { to { transform: translateY(112vh) rotate(720deg); } }`}</style>
    </div>
  );
}

function Ring({ fraction }: { fraction: number }) {
  const r = 11;
  const c = 2 * Math.PI * r;
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" className="-rotate-90">
      <circle cx="13" cy="13" r={r} fill="none" strokeWidth="2.2" className="stroke-line" />
      <circle
        cx="13"
        cy="13"
        r={r}
        fill="none"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - fraction)}
        className={clsx("transition-[stroke-dashoffset] duration-700", fraction >= 1 ? "stroke-ok" : "stroke-signal")}
      />
    </svg>
  );
}

/** One checklist row — shared by quest steps and daily challenges (a daily is a step with its
 *  own points and no skip state). */
function Row({
  item,
  points,
  open,
  onToggle,
  extra,
}: {
  item: { title: string; detail: string; href: string; cta: string; done: boolean; skipped?: boolean };
  points: number;
  open: boolean;
  onToggle: () => void;
  extra?: React.ReactNode;
}) {
  const complete = item.done || !!item.skipped;
  return (
    <li>
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-2.5 px-4 py-2 text-left">
        <span
          className={clsx(
            "grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border text-[10px] transition-colors",
            complete ? "border-ok/50 bg-ok/15 text-ok" : "border-line text-fg-faint",
          )}
        >
          {item.done ? "✓" : item.skipped ? "–" : ""}
        </span>
        <span
          className={clsx(
            "flex-1 truncate text-[13px]",
            complete ? "text-fg-muted line-through decoration-line" : "text-fg",
          )}
        >
          {item.title}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-fg-faint">
          {item.skipped && !item.done ? "skipped" : `+${points} xp`}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-3 pl-[42px]">
          <p className="text-[12px] leading-relaxed text-fg-muted">{item.detail}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {item.href && (
              <a href={item.href} className="btn-ghost">
                {item.cta} →
              </a>
            )}
            {extra}
          </div>
        </div>
      )}
    </li>
  );
}

export function OnboardingQuest() {
  const pathname = usePathname();
  const [local, setLocal] = useState<QuestLocal | null>(null); // null until mounted (SSR-safe)
  const [status, setStatus] = useState<QuestStatus>(EMPTY_STATUS);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [confetti, setConfetti] = useState(false);
  const autoOpened = useRef(false);
  const panel = useRef<HTMLDivElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);

  useEffect(() => setLocal(loadLocal()), []);
  useEffect(() => {
    if (local) localStorage.setItem(STORE, JSON.stringify(local));
  }, [local]);

  // tick page-visit steps (lifetime for the quest, per-day for the challenges) as the user moves
  // through the app; the theme step reads the toggle's own localStorage key.
  useEffect(() => {
    const m = visitMarker(pathname ?? "");
    const today = dayKey();
    setLocal((l) => {
      if (!l) return l;
      let next = l;
      if (m && !next.visited.includes(m)) next = { ...next, visited: [...next.visited, m] };
      const day = next.daily?.date === today ? next.daily : { date: today, visited: [], credited: [] };
      if (m && !day.visited.includes(m)) next = { ...next, daily: { ...day, visited: [...day.visited, m] } };
      if (!next.theme_touched && localStorage.getItem(THEME_KEY)) next = { ...next, theme_touched: true };
      return next;
    });
  }, [pathname]);

  // A topbar dropdown closes when you click past it or hit Escape — the quest used to be a
  // corner FAB, where neither applied. It also keeps this panel from overlapping the assistant,
  // which hangs in the same right-hand column.
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !launcher.current?.contains(t)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  // re-check the theme flag when the panel opens: toggling the theme causes no navigation
  useEffect(() => {
    if (!open) return;
    setLocal((l) => (l && !l.theme_touched && localStorage.getItem(THEME_KEY) ? { ...l, theme_touched: true } : l));
  }, [open]);

  // refresh the counts on every navigation — data-derived steps tick right after the deed
  useEffect(() => {
    if (local?.dismissed) return;
    fetch("/api/onboarding")
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (s) setStatus(s);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [pathname, local?.dismissed]);

  const today = dayKey();
  const steps = useMemo(() => (local ? deriveSteps(status, local) : []), [status, local]);
  const dailies = useMemo(
    () => (local ? deriveDailies(status, local.daily?.date === today ? local.daily.visited : [], today) : []),
    [status, local, today],
  );
  const complete = steps.filter(stepComplete).length;
  const total = steps.length;
  const allDone = total > 0 && complete === total;
  const score = complete * XP_PER_STEP + (local?.score ?? 0);
  const streak = local?.streak?.count ?? 0;

  // bank newly-completed dailies into score + streak (settleDaily returns null when settled)
  useEffect(() => {
    if (!local || !loaded) return;
    const settled = settleDaily(local, dailies, today);
    if (settled) setLocal(settled);
  }, [local, loaded, dailies, today]);

  // fresh workspaces get the panel once, uninvited; everyone else just sees the launcher
  useEffect(() => {
    if (!loaded || !local || local.opened || autoOpened.current) return;
    autoOpened.current = true;
    setLocal((l) => (l ? { ...l, opened: true } : l));
    if (complete < 3) setOpen(true);
  }, [loaded, local, complete]);

  // one celebration, ever
  useEffect(() => {
    if (!loaded || !local || !allDone || local.celebrated) return;
    setLocal((l) => (l ? { ...l, celebrated: true } : l));
    setConfetti(true);
    setOpen(true);
    const t = setTimeout(() => setConfetti(false), 4200);
    return () => clearTimeout(t);
  }, [loaded, local, allDone]);

  if (!local || local.dismissed) return null;

  const groups = [...new Set(steps.map((s) => s.group))];
  const firstUndone = steps.find((s) => !stepComplete(s))?.id ?? null;
  const expanded = openRow ?? firstUndone;

  const copyKey = status.ingest_key
    ? () => {
        navigator.clipboard?.writeText(status.ingest_key!).catch(() => {});
        setLocal((l) => (l ? { ...l, key_copied: true } : l));
      }
    : null;

  const overlay = (
    <>
      {confetti && <Confetti />}

      {open && (
        <div ref={panel} className="animate-fadeup fixed right-8 top-[64px] z-40 flex max-h-[min(680px,calc(100vh-80px))] w-[360px] flex-col overflow-hidden rounded-xl border border-line bg-ink-900 shadow-2xl">
          <div className="border-b border-line px-4 py-3">
            <div className="flex items-center justify-between">
              <h2 className="text-[13.5px] font-semibold text-fg">
                {allDone ? "Quest complete 🏆" : "Tracely quest"}
              </h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close quest"
                className="rounded-md px-1.5 text-[15px] leading-none text-fg-faint transition-colors hover:text-fg"
              >
                ×
              </button>
            </div>
            <div className="mt-2 flex items-center justify-between font-mono text-[10.5px] text-fg-faint">
              <span className={allDone ? "text-ok" : "text-signal"}>
                {score.toLocaleString()} xp · {questRank(complete, total)}
                {streak > 1 && <span className="text-warn"> · 🔥 {streak}-day streak</span>}
              </span>
              <span>
                {complete} / {total}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-900">
              <div
                className={clsx("h-full rounded-full transition-all duration-700", allDone ? "bg-ok/70" : "bg-signal/70")}
                style={{ width: `${total ? (complete / total) * 100 : 0}%` }}
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            <div className="px-4 pb-1 pt-3 font-mono text-[10px] uppercase tracking-[0.2em] text-warn/80">
              Today&apos;s challenges
            </div>
            <ol>
              {dailies.map((d) => (
                <Row
                  key={d.id}
                  item={d}
                  points={d.points}
                  open={expanded === `d:${d.id}`}
                  onToggle={() => setOpenRow(expanded === `d:${d.id}` ? "" : `d:${d.id}`)}
                />
              ))}
            </ol>

            {allDone ? (
              <div className="border-t border-line/50 px-4 py-6 text-center">
                <p className="text-[13px] text-fg">You&apos;ve run the whole loop — trace to gate.</p>
                <p className="mt-1.5 text-[12px] text-fg-muted">
                  The daily challenges above keep the score going; everything else runs itself.
                </p>
              </div>
            ) : (
              groups.map((g) => (
                <div key={g}>
                  <div className="px-4 pb-1 pt-3 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
                    {g}
                  </div>
                  <ol>
                    {steps
                      .filter((s) => s.group === g)
                      .map((s) => (
                        <Row
                          key={s.id}
                          item={s}
                          points={XP_PER_STEP}
                          open={expanded === s.id}
                          onToggle={() => setOpenRow(expanded === s.id ? "" : s.id)}
                          extra={
                            <>
                              {s.id === "key" && copyKey && (
                                <button type="button" onClick={copyKey} className="btn-ghost">
                                  Copy key
                                </button>
                              )}
                              {s.id === "llm" && !stepComplete(s) && (
                                <button
                                  type="button"
                                  onClick={() => setLocal((l) => (l ? { ...l, llm_skipped: true } : l))}
                                  className="btn-ghost"
                                >
                                  I don&apos;t have one — skip
                                </button>
                              )}
                            </>
                          }
                        />
                      ))}
                  </ol>
                </div>
              ))
            )}
          </div>

          <div className="flex items-center justify-between border-t border-line px-4 py-2">
            <span className="font-mono text-[10px] text-fg-faint">progress saved in this browser</span>
            <button
              type="button"
              onClick={() => setLocal((l) => (l ? { ...l, dismissed: true } : l))}
              className="font-mono text-[10px] text-fg-faint transition-colors hover:text-fail"
            >
              dismiss forever
            </button>
          </div>
        </div>
      )}
    </>
  );

  return (
    <>
      {/* The panel escapes to <body>: the Topbar this button lives in is a `sticky z-20` header,
          which is its own stacking context — a panel rendered inside it would slide under the
          app's portalled overlays (score popovers, drawers, the ⌘K palette). */}
      {typeof document !== "undefined" && createPortal(overlay, document.body)}

      <button
        ref={launcher}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Onboarding quest — ${complete} of ${total} steps done`}
        title={allDone ? "Quest complete" : `Tracely quest — ${complete}/${total}`}
        className="relative grid h-8 w-8 place-items-center rounded-lg border border-line bg-ink-800 transition-colors hover:border-signal/40"
      >
        <span className="absolute inset-[2px]">
          <Ring fraction={total ? complete / total : 0} />
        </span>
        <span className={clsx("font-mono text-[10px] font-semibold", allDone ? "text-ok" : "text-signal")}>
          {allDone ? (streak > 1 ? `🔥${streak}` : "✓") : complete}
        </span>
      </button>
    </>
  );
}
