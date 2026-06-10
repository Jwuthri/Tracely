"use client";

import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

// A self-contained popover date-range picker styled on the app's tokens (ink/line/signal). Selecting a
// range applies it as [start-of-day .. end-of-day] in the user's local zone; onApply receives ISO-8601
// (UTC) strings, or (null, null) when cleared. Replaces the native datetime-local inputs.
type Props = {
  from: string | null; // ISO-8601 (UTC) or null
  to: string | null; // ISO-8601 (UTC) or null
  disabled?: boolean;
  onApply: (from: string | null, to: string | null) => void;
};

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const startOfDay = (d: Date) => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
};
const endOfDay = (d: Date) => {
  const x = new Date(d);
  x.setHours(23, 59, 59, 999);
  return x;
};
const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
// integer key for day-level comparisons, ignoring time
const key = (d: Date) => d.getFullYear() * 10000 + d.getMonth() * 100 + d.getDate();

function monthCells(year: number, month: number): (Date | null)[] {
  const lead = new Date(year, month, 1).getDay();
  const total = new Date(year, month + 1, 0).getDate();
  const cells: (Date | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= total; d++) cells.push(new Date(year, month, d));
  return cells;
}

const fmtShort = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const fmtLong = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

export function DateRangePicker({ from, to, disabled, onApply }: Props) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<{ year: number; month: number }>({ year: 2000, month: 0 });
  const [start, setStart] = useState<Date | null>(null);
  const [end, setEnd] = useState<Date | null>(null);
  const [hover, setHover] = useState<Date | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const active = Boolean(from && to);
  const label = active ? `${fmtShort(from!)} – ${fmtLong(to!)}` : "Custom range";

  function openPicker() {
    if (disabled) return;
    const f = from ? new Date(from) : null;
    const t = to ? new Date(to) : null;
    setStart(f);
    setEnd(t);
    const base = f ?? new Date();
    setAnchor({ year: base.getFullYear(), month: base.getMonth() });
    setHover(null);
    setOpen(true);
  }

  // dismiss on outside-click or Escape
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function pick(day: Date) {
    // first click, or restarting after a complete range → set start, await end
    if (!start || (start && end)) {
      setStart(day);
      setEnd(null);
      return;
    }
    // second click → order the two ends and commit
    const [s, e] = key(day) < key(start) ? [day, start] : [start, day];
    setStart(s);
    setEnd(e);
    onApply(startOfDay(s).toISOString(), endOfDay(e).toISOString());
    setOpen(false);
  }

  function clear() {
    setStart(null);
    setEnd(null);
    onApply(null, null);
    setOpen(false);
  }

  function shift(months: number) {
    setAnchor((a) => {
      const d = new Date(a.year, a.month + months, 1);
      return { year: d.getFullYear(), month: d.getMonth() };
    });
  }

  const today = open ? new Date() : null;
  // preview end follows the cursor while only the start is chosen
  const effEnd = end ?? (start ? hover : null);
  const lo = start && effEnd ? (key(start) <= key(effEnd) ? start : effEnd) : null;
  const hi = start && effEnd ? (key(start) >= key(effEnd) ? start : effEnd) : null;

  function renderMonth(year: number, month: number) {
    return (
      <div className="w-[224px]">
        <div className="grid grid-cols-7">
          {WEEKDAYS.map((w, i) => (
            <div
              key={i}
              className="flex h-6 items-center justify-center font-mono text-[9.5px] uppercase tracking-wider text-fg-faint"
            >
              {w}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7" onMouseLeave={() => setHover(null)}>
          {monthCells(year, month).map((day, i) => {
            if (!day) return <div key={i} className="h-8" />;
            const inBand = !!(lo && hi && key(day) >= key(lo) && key(day) <= key(hi));
            const isLo = !!(lo && sameDay(day, lo));
            const isHi = !!(hi && sameDay(day, hi));
            const startOnly = !!(start && !effEnd && sameDay(day, start));
            const isEnd = (inBand && (isLo || isHi)) || startOnly;
            const isToday = today && sameDay(day, today);
            return (
              <div
                key={i}
                className={clsx(
                  "flex h-8 items-center justify-center",
                  inBand && !isEnd && "bg-signal/15",
                  inBand && isLo && "rounded-l-lg",
                  inBand && isHi && "rounded-r-lg",
                )}
              >
                <button
                  type="button"
                  onClick={() => pick(day)}
                  onMouseEnter={() => setHover(day)}
                  className={clsx(
                    "flex h-8 w-8 items-center justify-center rounded-lg text-[12px] transition-colors",
                    isEnd
                      ? "bg-signal font-semibold text-ink-900"
                      : inBand
                        ? "text-fg hover:bg-signal/25"
                        : "text-fg-muted hover:bg-ink-700 hover:text-fg",
                    isToday && !isEnd && !inBand && "text-signal",
                  )}
                >
                  {day.getDate()}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  const next = new Date(anchor.year, anchor.month + 1, 1);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={openPicker}
        disabled={disabled}
        className={clsx(
          "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-50",
          active
            ? "border-signal/50 bg-signal/15 text-signal"
            : "border-line bg-ink-800 text-fg-muted hover:text-fg",
        )}
      >
        <CalendarIcon />
        <span>{label}</span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-2 rounded-xl border border-line bg-ink-800 p-3 shadow-panel">
          <div className="flex items-start gap-4">
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => shift(-1)}
                  aria-label="Previous month"
                  className="flex h-6 w-6 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-ink-700 hover:text-fg"
                >
                  <Chevron dir="left" />
                </button>
                <span className="font-display text-[13px] text-fg">
                  {MONTHS[anchor.month]} {anchor.year}
                </span>
                <span className="h-6 w-6" />
              </div>
              {renderMonth(anchor.year, anchor.month)}
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="h-6 w-6" />
                <span className="font-display text-[13px] text-fg">
                  {MONTHS[next.getMonth()]} {next.getFullYear()}
                </span>
                <button
                  type="button"
                  onClick={() => shift(1)}
                  aria-label="Next month"
                  className="flex h-6 w-6 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-ink-700 hover:text-fg"
                >
                  <Chevron dir="right" />
                </button>
              </div>
              {renderMonth(next.getFullYear(), next.getMonth())}
            </div>
          </div>

          <div className="mt-2.5 flex items-center justify-between border-t border-line/70 pt-2.5">
            <span className="text-[11px] text-fg-faint">
              {start
                ? `${fmtShort(start.toISOString())} ${end ? `– ${fmtShort(end.toISOString())}` : "– …"}`
                : "Pick a start and end day"}
            </span>
            <button
              type="button"
              onClick={clear}
              className="rounded-lg border border-line bg-ink-800 px-2.5 py-1 text-[11px] font-medium text-fg-muted transition-colors hover:text-fg"
            >
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CalendarIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  );
}

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={dir === "left" ? "M15 18l-6-6 6-6" : "M9 18l6-6-6-6"} />
    </svg>
  );
}
