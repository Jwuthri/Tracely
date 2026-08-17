"use client";

// Right-side drawer showing the shared state object a conversation threaded through its graph —
// LangGraph's `State`, a hand-rolled scratchpad, a conversation-scoped store. Two views of the same
// folded data: what the state IS now, and the per-step deltas that got it there.
//
// Renders entirely from spans the caller already loaded (see state-fold.ts) — no fetch, no endpoint.
// Unchanged rewrites are hidden by default: a graph that re-emits the same channel on every node
// otherwise buries the two writes that actually mattered.

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { SpanOut } from "../lib/api";
import { HighlightedJson, prettyJson } from "./JsonView";
import { foldState, type StateChange } from "./state-fold";

export function StatePanel({
  threadId,
  spans,
  onClose,
}: {
  threadId: string;
  spans: SpanOut[];
  onClose: () => void;
}) {
  const { steps, final } = useMemo(() => foldState(spans), [spans]);
  const [showUnchanged, setShowUnchanged] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const visibleSteps = useMemo(
    () =>
      steps
        .map((s) => ({ ...s, changes: showUnchanged ? s.changes : s.changes.filter((c) => c.kind !== "same") }))
        .filter((s) => s.changes.length > 0),
    [steps, showUnchanged],
  );
  const hiddenCount = steps.length - visibleSteps.length;
  const finalKeys = Object.entries(final);

  return createPortal(
    <>
      <div className="fixed inset-0 z-[80] bg-black/50 backdrop-blur-[1px]" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-[81] flex w-full max-w-md flex-col border-l border-line bg-ink-900 shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-[14px] font-semibold text-fg">
              <StateIcon /> Conversation State
            </h2>
            <p className="mt-0.5 font-mono text-[11px] text-fg-faint">{threadId}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-fg-faint transition-colors hover:bg-hilite/5 hover:text-fg"
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {steps.length === 0 ? (
            <p className="mt-8 text-center text-[13px] text-fg-faint">
              No shared state recorded for this conversation.
              <br />
              <span className="text-[11.5px]">
                LangGraph node state is picked up automatically; otherwise record deltas with{" "}
                <code className="font-mono">tracely.set_state(&#123;…&#125;)</code>.
              </span>
            </p>
          ) : (
            <div className="space-y-5">
              <section>
                <SectionLabel>
                  Current{finalKeys.length > 0 && <span className="text-fg-muted"> · {finalKeys.length}</span>}
                </SectionLabel>
                <div className="space-y-1.5">
                  {finalKeys.map(([k, v]) => (
                    <ValueRow key={k} label={k} value={v} />
                  ))}
                </div>
              </section>

              <section>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <SectionLabel>
                    Timeline<span className="text-fg-muted"> · {visibleSteps.length}</span>
                  </SectionLabel>
                  <button
                    onClick={() => setShowUnchanged((v) => !v)}
                    className="font-mono text-[10px] text-fg-faint transition-colors hover:text-fg"
                  >
                    {showUnchanged ? "hide unchanged" : "show unchanged"}
                  </button>
                </div>
                <div className="space-y-3">
                  {visibleSteps.map((s) => (
                    <div key={s.span_id} className="rounded-lg border border-line bg-hilite/[0.02] p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[12.5px] font-semibold text-fg">{s.label}</span>
                        {s.agent_id && (
                          <span className="shrink-0 truncate font-mono text-[10px] text-fg-faint">{s.agent_id}</span>
                        )}
                      </div>
                      <div className="mt-2 space-y-1.5">
                        {s.changes.map((c) => (
                          <ValueRow key={c.key} label={c.key} value={c.value} kind={c.kind} />
                        ))}
                      </div>
                    </div>
                  ))}
                  {visibleSteps.length === 0 && (
                    <p className="text-[12px] text-fg-faint">
                      Every write in this conversation re-set a channel to the value it already had.
                    </p>
                  )}
                  {hiddenCount > 0 && !showUnchanged && (
                    <p className="text-[11px] text-fg-faint">
                      {hiddenCount} step{hiddenCount === 1 ? "" : "s"} changed nothing.
                    </p>
                  )}
                </div>
              </section>
            </div>
          )}
        </div>
      </aside>
    </>,
    document.body,
  );
}

const KIND_STYLE: Record<NonNullable<StateChange["kind"]>, string> = {
  add: "text-t_ok",
  update: "text-signal",
  same: "text-fg-faint",
};

// One click-to-expand channel. Collapsed shows a one-line preview, because a state channel is very
// often a whole message history and inlining it is what makes these views unreadable.
function ValueRow({ label, value, kind }: { label: string; value: unknown; kind?: StateChange["kind"] }) {
  const [open, setOpen] = useState(false);
  const isText = typeof value === "string";
  const body = isText ? value : (prettyJson(value) ?? "");
  const preview = isText
    ? value.replace(/\s+/g, " ").slice(0, 60)
    : Array.isArray(value)
      ? `${value.length} item${value.length === 1 ? "" : "s"}`
      : value === null || value === undefined
        ? String(value)
        : typeof value === "object"
          ? `${Object.keys(value as object).length} keys`
          : String(value);

  return (
    <div className="overflow-hidden rounded-md border border-line/70 bg-ink-950/60">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-hilite/[0.04]"
      >
        <Chevron open={open} />
        <span className="shrink-0 font-mono text-[11px] text-fg">{label}</span>
        {kind && (
          <span className={`shrink-0 font-mono text-[9px] uppercase tracking-wide ${KIND_STYLE[kind]}`}>
            {kind}
          </span>
        )}
        {!open && <span className="truncate text-[11px] text-fg-faint">{preview}</span>}
      </button>
      {open && (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-line/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-fg-muted">
          {isText ? body : <HighlightedJson text={body} />}
        </pre>
      )}
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
    >
      <path d="m9 18 6-6-6-6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-fg-faint">{children}</div>;
}

export function StateIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" className="text-signal">
      <ellipse cx="12" cy="6" rx="7.5" ry="3" stroke="currentColor" strokeWidth="1.7" />
      <path d="M4.5 6v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3V6" stroke="currentColor" strokeWidth="1.7" />
      <path d="M4.5 12v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-6" stroke="currentColor" strokeWidth="1.7" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
