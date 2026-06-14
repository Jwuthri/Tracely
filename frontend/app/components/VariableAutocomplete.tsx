"use client";

import clsx from "clsx";
import { useEffect, useRef, type SVGProps } from "react";

// Autocomplete dropdown for the advanced prompt editor. Purely presentational: the editor owns the
// candidate list, selection index, caret position, and insertion — this renders + reports hover/click.

export type AutocompleteItem = { name: string; description: string; isObject?: boolean };

const HashIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...p}>
    <line x1="4" x2="20" y1="9" y2="9" /><line x1="4" x2="20" y1="15" y2="15" />
    <line x1="10" x2="8" y1="3" y2="21" /><line x1="16" x2="14" y1="3" y2="21" />
  </svg>
);
const BracesIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1" />
    <path d="M16 3h1a2 2 0 0 1 2 2v5a2 2 0 0 0 2 2 2 2 0 0 0-2 2v5a2 2 0 0 1-2 2h-1" />
  </svg>
);
const ChevronR = (p: SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...p}><path d="m9 18 6-6-6-6" /></svg>
);

export function VariableAutocomplete({
  items,
  selected,
  position,
  prefix = "@",
  onSelect,
  onHover,
  onClose,
}: {
  items: AutocompleteItem[];
  selected: number;
  position: { top: number; left: number };
  prefix?: string; // "@" for top-level vars, "" for nested props
  onSelect: (index: number) => void;
  onHover: (index: number) => void;
  onClose: () => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  // keep the selected row scrolled into view as the user arrows through
  useEffect(() => {
    const el = listRef.current?.children[selected] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  // outside-click closes
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (listRef.current && !listRef.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);

  if (items.length === 0) return null;

  return (
    <div
      ref={listRef}
      className="absolute z-50 max-h-60 w-72 overflow-y-auto rounded-lg border border-line-bright bg-ink-800 py-1 shadow-2xl shadow-black/60"
      style={{ top: position.top, left: position.left }}
      role="listbox"
    >
      {items.map((it, i) => {
        const active = i === selected;
        return (
          <button
            key={it.name}
            type="button"
            role="option"
            aria-selected={active}
            // mousedown (not click) so the textarea doesn't lose focus before we insert
            onMouseDown={(e) => { e.preventDefault(); onSelect(i); }}
            onMouseEnter={() => onHover(i)}
            className={clsx(
              "flex w-full items-start gap-2.5 px-2.5 py-1.5 text-left transition-colors",
              active ? "bg-emerald-500/15" : "hover:bg-ink-700/60",
            )}
          >
            <span className={clsx(
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded",
              active ? "bg-emerald-500/20 text-emerald-300" : "bg-ink-700 text-fg-faint",
            )}>
              {it.isObject ? <BracesIcon className="h-3 w-3" /> : <HashIcon className="h-3 w-3" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5">
                <span className={clsx("font-mono text-[12px] font-semibold", active ? "text-emerald-300" : "text-emerald-400")}>
                  {prefix}{it.name}
                </span>
                {it.isObject && (
                  <span className="rounded bg-ink-700 px-1 py-px text-[8.5px] font-medium uppercase tracking-wider text-fg-faint">
                    object
                  </span>
                )}
                {it.isObject && <ChevronR className="h-3 w-3 text-fg-faint" />}
              </span>
              <span className="mt-0.5 block truncate text-[10.5px] text-fg-faint">{it.description}</span>
            </span>
          </button>
        );
      })}
      <div className="mt-0.5 flex items-center justify-end gap-2 border-t border-line px-2.5 pt-1 text-[9px] text-fg-faint/70">
        <span>↑↓ navigate</span><span>↵ insert</span><span>esc close</span>
      </div>
    </div>
  );
}
