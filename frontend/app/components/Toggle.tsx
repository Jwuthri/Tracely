"use client";

import clsx from "clsx";

/** A themed on/off switch.
 *
 *  Same idiom as `SelectBox`: the real `<input>` stays in the DOM (`sr-only`) so keyboard and
 *  screen readers get a genuine checkbox, and `peer-*` classes paint the visible track. A native
 *  checkbox with `accent-signal` — what this replaces — renders as the OS control and reads as
 *  foreign next to every other surface in the app. */
export function Toggle({
  checked,
  onChange,
  label,
  className,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** Accessible name; also rendered as the visible caption. */
  label: string;
  className?: string;
}) {
  return (
    <label
      className={clsx(
        "group/toggle inline-flex cursor-pointer select-none items-center gap-2",
        className,
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        aria-label={label}
        className="peer sr-only"
      />
      <span
        className={clsx(
          "relative h-[18px] w-[32px] rounded-full border transition-colors",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-signal/40",
          checked
            ? "border-signal/50 bg-signal/25"
            : "border-line-bright bg-ink-900/80 group-hover/toggle:border-line-bright",
        )}
      >
        <span
          className={clsx(
            "absolute top-1/2 h-[12px] w-[12px] -translate-y-1/2 rounded-full transition-all",
            checked ? "left-[16px] bg-signal shadow-[0_0_8px_rgba(34,211,238,0.6)]" : "left-[2px] bg-fg-faint",
          )}
        />
      </span>
      <span
        className={clsx(
          "font-mono text-[11px] transition-colors",
          checked ? "text-fg-muted" : "text-fg-faint",
        )}
      >
        {label}
      </span>
    </label>
  );
}
