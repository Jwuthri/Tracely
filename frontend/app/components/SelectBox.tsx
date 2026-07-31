"use client";

import clsx from "clsx";
import { useEffect, useRef } from "react";

/** The app's multi-select checkbox (traces table + cluster list).
 *
 * The native input is the a11y/interaction surface (sr-only); the visible box is styled with the
 * ink/line/signal tokens. The 24px label is the hit target and swallows the click so a row that
 * navigates on click never fires from ticking a box. */
export function SelectBox({
  checked,
  indeterminate = false,
  onChange,
  label,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: () => void;
  label: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <label
      onClick={(e) => e.stopPropagation()}
      title={label}
      className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-ink-600/70"
    >
      <input ref={ref} type="checkbox" checked={checked} onChange={onChange} aria-label={label} className="peer sr-only" />
      <span className="flex h-[15px] w-[15px] items-center justify-center rounded-[4px] border border-line-bright bg-ink-900/80 transition-colors peer-hover:border-signal/60 peer-checked:border-signal peer-checked:bg-signal peer-focus-visible:ring-2 peer-focus-visible:ring-signal/40">
        {indeterminate ? (
          <span className="h-[2px] w-2 rounded-full bg-signal" />
        ) : (
          <svg viewBox="0 0 12 12" className={clsx("h-2.5 w-2.5 text-ink-900 transition-opacity", checked ? "opacity-100" : "opacity-0")} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2.5 6.4 4.8 8.7 9.5 3.6" />
          </svg>
        )}
      </span>
    </label>
  );
}
