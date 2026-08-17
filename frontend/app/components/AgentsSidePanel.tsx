"use client";

// Right-side drawer listing a conversation's agents. Two sources:
//   • DECLARED — the rich catalog the user sent via the SDK (tracely.trace(agents=[...])): name,
//     description, and tools with parameters. Annotated with how often each tool actually ran.
//     Any OTHER key declared (system_prompt, model, guardrails, config, …) renders as its own
//     expandable row — the catalog is free-form, so the panel must not assume a fixed shape.
//   • OBSERVED — agents derived from the trace spans (agent id, tools used, plus the system prompt
//     and models recovered from the spans themselves), the fallback when nothing was declared.
// Everything here is click-to-expand: prompts, tool schemas, and arbitrary config blobs are all
// too big to render inline. Rendered via a portal so it escapes the table/timeline overflow.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { HighlightedJson, prettyJson } from "./JsonView";

type DeclaredTool = { name: string; description: string; parameters: Record<string, unknown>; count: number } & Record<string, unknown>;
type DeclaredAgent = { name: string; description: string; tools: DeclaredTool[] } & Record<string, unknown>;
type ObservedTool = { name: string; count: number };
type ObservedAgent = {
  agent_id: string; name: string; slug: string; tools: ObservedTool[]; span_count: number;
  system_prompt?: string; models?: string[];
};
type AgentsData = { declared: DeclaredAgent[]; observed: ObservedAgent[] };

// Keys the card renders itself — everything else becomes a generic expandable row.
const DECLARED_OWN = new Set(["name", "description", "tools"]);
const TOOL_OWN = new Set(["name", "description", "parameters", "count"]);

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
            className="rounded-md p-1.5 text-fg-faint transition-colors hover:bg-hilite/5 hover:text-fg"
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {data === null ? (
            <div className="space-y-3">
              <div className="h-24 animate-pulse rounded-lg bg-hilite/[0.03]" />
              <div className="h-24 animate-pulse rounded-lg bg-hilite/[0.03]" />
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
                      <div key={`${a.name}-${i}`} className="rounded-lg border border-line bg-hilite/[0.02] p-4">
                        <div className="text-[13.5px] font-semibold text-fg">{a.name}</div>
                        {a.description && (
                          <div className="mt-0.5 text-[12px] text-fg-muted">{a.description}</div>
                        )}

                        {/* every key the card doesn't render itself — system_prompt, model, guardrails, … */}
                        {Object.entries(a)
                          .filter(([k, v]) => !DECLARED_OWN.has(k) && v != null && v !== "")
                          .map(([k, v]) => <ConfigRow key={k} label={k} value={v} />)}

                        <div className="mt-3 space-y-1.5">
                          <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
                            Tools{a.tools.length > 0 && <span className="text-fg-muted"> · {a.tools.length}</span>}
                          </div>
                          {a.tools.length === 0 ? (
                            <p className="text-[12px] text-fg-faint">No tools declared.</p>
                          ) : (
                            a.tools.map((t) => <ToolRow key={t.name} tool={t} />)
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* ponytail: declared wins outright — the observed view duplicates it and reads badly */}
              {data.declared.length === 0 && data.observed.length > 0 && (
                <section>
                  <SectionLabel>Agents</SectionLabel>
                  <div className="space-y-3">
                    {data.observed.map((a) => (
                      <div key={a.agent_id || a.name} className="rounded-lg border border-line bg-hilite/[0.02] p-4">
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

                        {/* recovered from the agent's own spans, not declared by anyone */}
                        {a.system_prompt && <ConfigRow label="system_prompt" value={a.system_prompt} derived />}
                        {a.models && a.models.length > 0 && (
                          <ConfigRow label="models" value={a.models} derived />
                        )}

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
                                  className="inline-flex items-center gap-1.5 rounded-md border border-line bg-hilite/[0.04] px-2 py-1 font-mono text-[11px] text-fg-muted"
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

// One click-to-expand config row. Strings render as wrapped text (prompts), everything else as
// highlighted JSON. `derived` marks values Tracely recovered from the trace rather than was told.
function ConfigRow({ label, value, derived }: { label: string; value: unknown; derived?: boolean }) {
  const [open, setOpen] = useState(false);
  const isText = typeof value === "string";
  const body = isText ? (value as string) : prettyJson(value) ?? "";
  const preview = isText
    ? (value as string).replace(/\s+/g, " ").slice(0, 60)
    : Array.isArray(value)
      ? `${value.length} item${value.length === 1 ? "" : "s"}`
      : `${Object.keys(value as object).length} keys`;

  return (
    <div className="mt-2 overflow-hidden rounded-md border border-line/70 bg-ink-950/60">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-hilite/[0.04]"
      >
        <Chevron open={open} />
        <span className="font-mono text-[11px] text-fg">{label}</span>
        {derived && (
          <span
            title="recovered from the trace, not declared"
            className="rounded border border-line bg-hilite/[0.04] px-1 py-px font-mono text-[9px] uppercase tracking-wide text-fg-faint"
          >
            derived
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

// A declared tool: name + run count always visible, full parameter schema + any extra keys on click.
function ToolRow({ tool }: { tool: DeclaredTool }) {
  const [open, setOpen] = useState(false);
  const extras = Object.fromEntries(Object.entries(tool).filter(([k]) => !TOOL_OWN.has(k)));
  const params = tool.parameters || {};
  const hasDetail = Object.keys(params).length > 0 || Object.keys(extras).length > 0;

  return (
    <div className="overflow-hidden rounded-md border border-line/70 bg-ink-950/60">
      <button
        onClick={() => hasDetail && setOpen((o) => !o)}
        aria-expanded={hasDetail ? open : undefined}
        className={`w-full px-2.5 py-1.5 text-left transition-colors ${hasDetail ? "hover:bg-hilite/[0.04]" : "cursor-default"}`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5 font-mono text-[11.5px] text-fg">
            {hasDetail ? <Chevron open={open} /> : <span className="h-1.5 w-1.5 rounded-[3px] bg-t_tool" />}
            <span className="truncate">{tool.name}</span>
          </span>
          <span
            className="shrink-0 font-mono text-[10px] text-fg-faint"
            title={tool.count ? `executed ${tool.count}×` : "not executed in this conversation"}
          >
            {tool.count > 0 ? `×${tool.count}` : "unused"}
          </span>
        </div>
        {tool.description && (
          <div className="mt-0.5 text-[11.5px] text-fg-muted">{tool.description}</div>
        )}
        {!open && Object.keys(params).length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {Object.keys(params).map((p) => (
              <span
                key={p}
                className="rounded border border-line bg-hilite/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-fg-faint"
              >
                {p}
              </span>
            ))}
          </div>
        )}
      </button>
      {open && (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-line/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-fg-muted">
          <HighlightedJson text={prettyJson({ ...extras, parameters: params }) ?? ""} />
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
