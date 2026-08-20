"use client";

import clsx from "clsx";
import { memo, useContext, useMemo } from "react";
import { useRouter } from "next/navigation";
import type { ConvNode, FullTurn, SpanOut } from "../../lib/api";
import { SelectBox } from "../SelectBox";
import { normalizeType } from "../ui";
import { agentLabel, deriveTitle, sortSpans } from "./format";
import { type Col, CTRL, ROW_BG } from "./columns";
import { Bot, ChevronR, Play } from "./icons";
import { EvalViewContext, SelectContext, useCtrlCount } from "./contexts";
import { convHref, CopyConvButton, renderCell, type RowCtx } from "./cells";
import type { Cache } from "./useConversationTree";

// The row levels — conversation → turn → span — and the shared <tr> shell they all render
// through. Lazy: a conversation's turns and a turn's spans load when the row is expanded.

// ── rows ────────────────────────────────────────────────────────────────────────
// The per-row Play button: C rows evaluate the whole thread (turns + conversation metrics),
// M/S rows re-evaluate their turn. Spins while that scope is running.
function RowRunButton({ ctx }: { ctx: RowCtx }) {
  const view = useContext(EvalViewContext);
  if (!view.hasEvaluators) return null;
  const busy =
    ctx.level === "C"
      ? view.busyRows.has(`th:${ctx.conv.thread}`)
      : view.busyRows.has(`tr:${ctx.turn.trace_id}`) ||
        (ctx.level === "M" && view.busyRows.has(`th:${ctx.conv.thread}`));
  if (busy) {
    return (
      <span className="inline-flex h-6 w-6 items-center justify-center" title="Evaluating…">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-signal" />
      </span>
    );
  }
  return (
    <button
      tabIndex={-1}
      onClick={(e) => {
        e.stopPropagation();
        if (ctx.level === "C") view.runThread(ctx.conv.thread);
        else view.runTrace(ctx.turn.trace_id);
      }}
      className="inline-flex h-6 w-6 items-center justify-center rounded-lg opacity-0 transition-opacity hover:bg-ink-600 group-hover:opacity-100"
      title={ctx.level === "C" ? "Run all evaluations for this conversation" : "Run all evaluations for this turn"}
    >
      <Play className="h-3 w-3 text-fg-muted" />
    </button>
  );
}

function DataRow({
  depth,
  ctx,
  cols,
  canExpand,
  open,
  onToggle,
  agentCount,
  onShowAgents,
}: {
  depth: 0 | 1 | 2;
  ctx: RowCtx;
  cols: Col[];
  canExpand?: boolean;
  open?: boolean;
  onToggle?: () => void;
  agentCount?: number;
  onShowAgents?: (thread: string) => void;
}) {
  const router = useRouter();
  const sel = useContext(SelectContext);
  // Whole-row click zooms in — but only at the conversation and message levels. Step (S) rows are
  // NOT row-clickable (too easy to mis-click while reading); their expandable objects/pills still
  // work on their own. Clicks on interactive elements (chevron, pills, links) are always left alone.
  const isStep = ctx.level === "S";
  const href = ctx.level === "C" ? convHref(ctx.conv) : `/traces/${ctx.turn.trace_id}`;
  return (
    <tr
      onClick={
        isStep
          ? undefined
          : (e) => {
              if ((e.target as HTMLElement).closest("button, a, input, label")) return;
              router.push(href);
            }
      }
      className={clsx(
        "group border-b border-l-2 border-line-soft transition-colors hover:bg-ink-700/80",
        !isStep && "cursor-pointer",
        ROW_BG[depth],
      )}
    >
      {sel.enabled && (
        <td style={CTRL} className="px-2 py-2 align-top first:pl-2 sm:px-3 sm:first:pl-4">
          {ctx.level === "C" ? (
            <SelectBox
              checked={sel.selected.has(ctx.conv.thread)}
              onChange={() => sel.toggle(ctx.conv.thread)}
              label={`Select "${deriveTitle(ctx.conv.first_input)}"`}
            />
          ) : null}
        </td>
      )}
      <td style={CTRL} className="px-2 py-2 align-top first:pl-2 sm:px-3 sm:first:pl-4">
        {canExpand ? (
          <button onClick={onToggle} className="rounded p-1 transition-colors hover:bg-ink-600" aria-label={open ? "Collapse" : "Expand"}>
            <ChevronR className={clsx("h-4 w-4 text-fg-muted transition-transform", open && "rotate-90")} />
          </button>
        ) : (
          <div className="w-4" />
        )}
      </td>
      <td style={CTRL} className="px-2 py-2 align-top sm:px-3">
        <RowRunButton ctx={ctx} />
      </td>
      <td style={CTRL} className="px-2 py-2 align-top sm:px-3">
        {ctx.level === "C" ? <CopyConvButton thread={ctx.conv.thread} /> : null}
      </td>
      <td style={CTRL} className="px-2 py-2 align-top sm:px-3">
        {ctx.level === "C" ? (
          <button
            tabIndex={-1}
            onClick={(e) => {
              e.stopPropagation();
              onShowAgents?.(ctx.conv.thread);
            }}
            className="inline-flex h-6 w-6 items-center justify-center rounded-lg opacity-0 transition-opacity hover:bg-ink-600 group-hover:opacity-100"
            title={`View ${agentCount ?? 1} agent${(agentCount ?? 1) === 1 ? "" : "s"}`}
          >
            <Bot className="h-3 w-3 text-fg-muted" />
          </button>
        ) : null}
      </td>
      {cols.map((col, i) => (
        <td
          key={col.key}
          style={{ width: col.width, minWidth: 80 }}
          className={clsx(
            "px-2 py-2 align-top text-sm text-fg sm:px-3",
            (col.evaluator || (i > 0 && cols[i - 1].group !== col.group)) && "border-l border-line-bright/50",
            col.tint?.td,
          )}
        >
          {renderCell(col, ctx)}
        </td>
      ))}
    </tr>
  );
}

// memo: a turn's step rows depend only on (turn, spans, cols, hiddenTypes) — all referentially stable
// across unrelated parent re-renders (busy/prefs/another thread expanding), so they skip re-rendering.
const SpanRows = memo(function SpanRows({ turn, spans, cols, hiddenTypes }: { turn: FullTurn; spans: SpanOut[]; cols: Col[]; hiddenTypes: Set<string> }) {
  // Applies to every step, recordings included. Tracely's own eval/sim spans used to opt out —
  // which made the Types filter a no-op on the conversation Evals page while the Timeline tab
  // (Waterfall) filtered them normally, so the same menu did different things in the two tabs.
  // The opt-out was there because a stale "hide CHAIN" pref blanked the view with no explanation;
  // the count badge on the Types button plus its Reset say so now, and the empty row below names it.
  const visible = sortSpans(spans).filter((s) => !hiddenTypes.has(normalizeType(s.type)));
  if (visible.length === 0) {
    return <EmptyTr cols={cols} text={spans.length ? "All step types hidden." : "No steps."} />;
  }
  return (
    <>
      {visible.map((span, i) => (
        <DataRow key={span.span_id} depth={2} cols={cols} ctx={{ level: "S", span, index: i + 1, turn }} />
      ))}
    </>
  );
});

function TurnRows({
  conv,
  turn,
  turnPos,
  spans,
  cols,
  hiddenTypes,
  open,
  onToggleTurn,
}: {
  conv: ConvNode;
  turn: FullTurn;
  turnPos: number;
  spans: SpanOut[] | "loading" | undefined;
  cols: Col[];
  hiddenTypes: Set<string>;
  open: boolean;
  onToggleTurn: (t: string) => void;
}) {
  return (
    <>
      {turn.input && <DataRow depth={1} cols={cols} ctx={{ level: "M", role: "user", conv, turn, index: turnPos * 2 + 1 }} />}
      <DataRow depth={1} cols={cols} ctx={{ level: "M", role: "assistant", conv, turn, index: turnPos * 2 + 2 }} canExpand open={open} onToggle={() => onToggleTurn(turn.trace_id)} />
      {open &&
        (spans === "loading" || spans === undefined ? (
          <LoadingTr cols={cols} />
        ) : spans.length === 0 ? (
          <EmptyTr cols={cols} text="No steps." />
        ) : (
          <SpanRows turn={turn} spans={spans} cols={cols} hiddenTypes={hiddenTypes} />
        ))}
    </>
  );
}

export function ConvRows({
  conv,
  turns,
  spansCache,
  open,
  openTurn,
  cols,
  hiddenTypes,
  onToggleConv,
  onToggleTurn,
  onShowAgents,
}: {
  conv: ConvNode;
  turns: FullTurn[] | "loading" | undefined;
  spansCache: Cache<SpanOut[]>;
  open: boolean;
  openTurn: Set<string>;
  cols: Col[];
  hiddenTypes: Set<string>;
  onToggleConv: (t: string) => void;
  onToggleTurn: (t: string) => void;
  onShowAgents: (thread: string) => void;
}) {
  const agentCount = useMemo(() => {
    if (!conv.turnsData) return 1;
    const set = new Set<string>();
    for (const t of conv.turnsData) for (const s of t.spans) {
      const a = agentLabel(s);
      if (a) set.add(a);
    }
    return set.size || 1;
  }, [conv]);

  return (
    <>
      <DataRow depth={0} cols={cols} ctx={{ level: "C", conv, agentCount }} canExpand open={open} onToggle={() => onToggleConv(conv.thread)} agentCount={agentCount} onShowAgents={onShowAgents} />
      {open &&
        (turns === "loading" || turns === undefined ? (
          <LoadingTr cols={cols} />
        ) : turns.length === 0 ? (
          <EmptyTr cols={cols} text="No messages." />
        ) : (
          turns.map((turn, i) => (
            <TurnRows key={turn.trace_id} conv={conv} turn={turn} turnPos={i} spans={spansCache[turn.trace_id]} cols={cols} hiddenTypes={hiddenTypes} open={openTurn.has(turn.trace_id)} onToggleTurn={onToggleTurn} />
          ))
        ))}
    </>
  );
}

function LoadingTr({ cols }: { cols: Col[] }) {
  return (
    <tr className="border-b border-line-soft bg-ink-700/20">
      <td colSpan={useCtrlCount() + cols.length} className="px-6 py-3 text-sm text-fg-faint">
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-fg-muted" />
          loading…
        </span>
      </td>
    </tr>
  );
}

function EmptyTr({ cols, text }: { cols: Col[]; text: string }) {
  return (
    <tr className="border-b border-line-soft bg-ink-700/20">
      <td colSpan={useCtrlCount() + cols.length} className="px-6 py-3 text-sm text-fg-faint">
        {text}
      </td>
    </tr>
  );
}

