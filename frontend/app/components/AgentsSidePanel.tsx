"use client";

// Right-side drawer listing a conversation's agents. Two sources:
//   • DECLARED — the rich catalog the user sent via the SDK (tracely.trace(agents=[...])): name,
//     description, and tools with parameters. Annotated with how often each tool actually ran.
//   • OBSERVED — agents derived from the trace spans (agent id + tools used), the fallback when
//     nothing was declared.
// Rendered via a portal so it escapes the table/timeline overflow containers.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type DeclaredTool = { name: string; description: string; parameters: Record<string, unknown>; count: number };
type DeclaredAgent = { name: string; description: string; tools: DeclaredTool[] };
type ObservedTool = { name: string; count: number };
type ObservedAgent = { agent_id: string; name: string; slug: string; tools: ObservedTool[]; span_count: number };
type AgentsData = { declared: DeclaredAgent[]; observed: ObservedAgent[] };

export function AgentsSidePanel({ threadId, onClose }: { threadId: string; onClose: () => void }) {
  const [data, setData] = useState<AgentsData | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`/api/sessions/${encodeURIComponent(threadId)}/agents`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!live) return;
        setData({
          declared: Array.isArray(d?.declared) ? d.declared : [],
          observed: Array.isArray(d?.observed) ? d.observed : [],
        });
      })
      .catch(() => live && setData({ declared: [], observed: [] }));
    return () => {
      live = false;
    };
  }, [threadId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const empty = data && data.declared.length === 0 && data.observed.length === 0;

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
          {data === null ? (
            <div className="space-y-3">
              <div className="h-24 animate-pulse rounded-lg bg-white/[0.03]" />
              <div className="h-24 animate-pulse rounded-lg bg-white/[0.03]" />
            </div>
          ) : empty ? (
            <p className="mt-8 text-center text-[13px] text-fg-faint">
              No agents found for this conversation.
              <br />
              <span className="text-[11.5px]">
                Declare them via <code className="font-mono">tracely.trace(agents=[…])</code> in the SDK.
              </span>
            </p>
          ) : (
            <div className="space-y-5">
              {data.declared.length > 0 && (
                <section>
                  <SectionLabel>Declared</SectionLabel>
                  <div className="space-y-3">
                    {data.declared.map((a, i) => (
                      <div key={`${a.name}-${i}`} className="rounded-lg border border-line bg-white/[0.02] p-4">
                        <div className="text-[13.5px] font-semibold text-fg">{a.name}</div>
                        {a.description && (
                          <div className="mt-0.5 text-[12px] text-fg-muted">{a.description}</div>
                        )}
                        <div className="mt-3 space-y-1.5">
                          <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
                            Tools{a.tools.length > 0 && <span className="text-fg-muted"> · {a.tools.length}</span>}
                          </div>
                          {a.tools.length === 0 ? (
                            <p className="text-[12px] text-fg-faint">No tools declared.</p>
                          ) : (
                            a.tools.map((t) => (
                              <div key={t.name} className="rounded-md border border-line/70 bg-black/20 px-2.5 py-1.5">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="flex items-center gap-1.5 font-mono text-[11.5px] text-fg">
                                    <span className="h-1.5 w-1.5 rounded-[3px] bg-t_tool" />
                                    {t.name}
                                  </span>
                                  <span
                                    className="shrink-0 font-mono text-[10px] text-fg-faint"
                                    title={t.count ? `executed ${t.count}×` : "not executed in this conversation"}
                                  >
                                    {t.count > 0 ? `×${t.count}` : "unused"}
                                  </span>
                                </div>
                                {t.description && (
                                  <div className="mt-0.5 text-[11.5px] text-fg-muted">{t.description}</div>
                                )}
                                {Object.keys(t.parameters || {}).length > 0 && (
                                  <div className="mt-1 flex flex-wrap gap-1">
                                    {Object.keys(t.parameters).map((p) => (
                                      <span
                                        key={p}
                                        className="rounded border border-line bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-fg-faint"
                                      >
                                        {p}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {data.observed.length > 0 && (
                <section>
                  <SectionLabel>{data.declared.length > 0 ? "Observed in traces" : "Agents"}</SectionLabel>
                  <div className="space-y-3">
                    {data.observed.map((a) => (
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
                </section>
              )}
            </div>
          )}
        </div>
      </aside>
    </>,
    document.body,
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2 font-mono text-[10.5px] uppercase tracking-[0.18em] text-fg-faint">{children}</div>
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
