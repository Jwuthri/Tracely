"use client";

import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

type Result = { type: string; label: string; sub: string; href: string };

const TYPE_CLR: Record<string, string> = {
  trace: "text-signal",
  issue: "text-fail",
  case: "text-t_tool",
  gate: "text-ok",
};

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [active, setActive] = useState(0);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("tracely:cmdk", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("tracely:cmdk", onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQ("");
      setResults([]);
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    const id = setTimeout(async () => {
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        setResults(await r.json());
        setActive(0);
      } catch {
        setResults([]);
      }
    }, 150);
    return () => clearTimeout(id);
  }, [q, open]);

  function go(r?: Result) {
    const target = r ?? results[active];
    if (target) {
      setOpen(false);
      router.push(target.href);
    }
  }

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-line bg-ink-800 shadow-glow"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              go();
            }
          }}
          placeholder="Search conversations, issues, cases, gates…"
          className="w-full border-b border-line bg-transparent px-4 py-3.5 text-[14px] text-fg placeholder:text-fg-faint focus:outline-none"
        />
        <div className="max-h-[50vh] overflow-auto py-1">
          {q.trim().length < 2 ? (
            <div className="px-4 py-6 text-center text-[12.5px] text-fg-faint">Type at least 2 characters…</div>
          ) : results.length === 0 ? (
            <div className="px-4 py-6 text-center text-[12.5px] text-fg-faint">No matches.</div>
          ) : (
            results.map((r, i) => (
              <button
                key={i}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(r)}
                className={clsx("flex w-full items-center gap-3 px-4 py-2.5 text-left", i === active && "bg-signal/[0.08]")}
              >
                <span className={clsx("w-12 shrink-0 font-mono text-[10px] uppercase tracking-wider", TYPE_CLR[r.type] ?? "text-fg-faint")}>
                  {r.type}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{r.label}</span>
                <span className="shrink-0 font-mono text-[10.5px] text-fg-faint">{r.sub}</span>
              </button>
            ))
          )}
        </div>
        <div className="flex items-center justify-between border-t border-line px-4 py-2 font-mono text-[10px] text-fg-faint">
          <span>↑↓ navigate · ↵ open · esc close</span>
          <span>⌘K</span>
        </div>
      </div>
    </div>
  );
}
