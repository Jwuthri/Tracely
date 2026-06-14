"use client";

// Right-side drawer listing the agents that took part in a conversation and the tools each used.
// Optional metadata derived from the thread's spans — when traces carry only a single default
// agent it shows that one agent (often with no tools). Rendered via a portal so it escapes the
// table/timeline overflow containers.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type Tool = { name: string; count: number };
type ConvAgent = {
  agent_id: string;
  name: string;
  slug: string;
  tools: Tool[];
  span_count: number;
  tool_call_count: number;
};

export function AgentsSidePanel({ threadId, onClose }: { threadId: string; onClose: () => void }) {
  const [agents, setAgents] = useState<ConvAgent[] | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`/api/sessions/${encodeURIComponent(threadId)}/agents`)
      .then((r) => (r.ok ? r.json() : { agents: [] }))
      .then((d) => live && setAgents(Array.isArray(d?.agents) ? d.agents : []))
      .catch(() => live && setAgents([]));
    return () => {
      live = false;
    };
  }, [threadId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <>
      <div className="fixed inset-0 z-[80] bg-black/50 backdrop-blur-[1px]" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-[81] flex w-full max-w-md flex-col border-l border-line bg-ink-900 shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-[14px] font-semibold text-fg">
              <BotIcon /> Conversation Agents
            </h2>
            <p className="mt-0.5 font-mono text-[11px] text-fg-faint">{threadId}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-fg-faint transition-colors hover:bg-white/5 hover:text-fg"
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {agents === null ? (
            <div className="space-y-3">
              <div className="h-24 animate-pulse rounded-lg bg-white/[0.03]" />
              <div className="h-24 animate-pulse rounded-lg bg-white/[0.03]" />
            </div>
          ) : agents.length === 0 ? (
            <p className="mt-8 text-center text-[13px] text-fg-faint">
              No agents found for this conversation.
            </p>
          ) : (
            <div className="space-y-3">
              {agents.map((a) => (
                <div key={a.agent_id || a.name} className="rounded-lg border border-line bg-white/[0.02] p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-[13.5px] font-semibold text-fg">{a.name}</div>
                      {a.slug && a.slug !== a.name && (
                        <div className="truncate font-mono text-[10.5px] text-fg-faint">{a.slug}</div>
                      )}
                    </div>
                    <span className="shrink-0 font-mono text-[10.5px] text-fg-faint">
                      {a.span_count} span{a.span_count === 1 ? "" : "s"}
                    </span>
                  </div>

                  <div className="mt-3">
                    <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
                      Tools {a.tools.length > 0 && <span className="text-fg-muted">· {a.tools.length}</span>}
                    </div>
                    {a.tools.length === 0 ? (
                      <p className="text-[12px] text-fg-faint">No tools observed.</p>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {a.tools.map((t) => (
                          <span
                            key={t.name}
                            title={t.count ? `${t.count} call${t.count === 1 ? "" : "s"}` : "requested, no execution span"}
                            className="inline-flex items-center gap-1.5 rounded-md border border-line bg-white/[0.04] px-2 py-1 font-mono text-[11px] text-fg-muted"
                          >
                            <span className="h-1.5 w-1.5 rounded-[3px] bg-t_tool" />
                            {t.name}
                            {t.count > 0 && <span className="text-fg-faint">×{t.count}</span>}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </>,
    document.body,
  );
}

function BotIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" className="text-signal">
      <rect x="4" y="8" width="16" height="11" rx="2.5" stroke="currentColor" strokeWidth="1.7" />
      <path d="M12 4v4M9 13h.01M15 13h.01" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <circle cx="12" cy="3.5" r="1.2" fill="currentColor" />
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
