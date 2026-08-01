"use client";

import clsx from "clsx";
import { useState } from "react";
import type { ScenarioTurn } from "@/app/lib/api";
import { IconChevron, IconX } from "./icons";

const FIELD =
  "w-full rounded-lg border border-line bg-ink-700 px-2.5 py-2 font-mono text-[12.5px] text-fg placeholder:text-fg-faint transition-colors hover:border-line-bright focus:border-signal/50 focus:outline-none";
const LABEL = "font-mono text-[10px] uppercase tracking-wider text-fg-faint";

export const emptyTurn = (): ScenarioTurn => ({ message: "", expect: "", tools: [] });

/** The multi-turn conversation editor.
 *
 *  One row per turn, because a turn is a message — not a line. The earlier one-per-line textarea
 *  broke the moment a message contained a newline, which is most real support messages, and left
 *  nowhere to hang per-turn expectations.
 *
 *  Expectations are collapsed by default and optional. A turn with none is graded by the
 *  project's own evaluators, exactly like production traffic; filling them in adds precision a
 *  generic judge can't have. Keeping them behind a toggle is what stops the form from looking
 *  like homework. */
export function TurnEditor({
  turns,
  onChange,
  toolsEnabled = true,
  idPrefix = "turn",
}: {
  turns: ScenarioTurn[];
  onChange: (next: ScenarioTurn[]) => void;
  toolsEnabled?: boolean;
  /** Namespaces the field ids — two editors can be open at once (create + edit). */
  idPrefix?: string;
}) {
  const update = (i: number, patch: Partial<ScenarioTurn>) =>
    onChange(turns.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const remove = (i: number) => onChange(turns.filter((_, j) => j !== i));
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= turns.length) return;
    const next = [...turns];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <div className={LABEL}>Conversation</div>
      {turns.map((turn, i) => (
        <TurnRow
          key={i}
          index={i}
          turn={turn}
          total={turns.length}
          toolsEnabled={toolsEnabled}
          idPrefix={idPrefix}
          onPatch={(patch) => update(i, patch)}
          onRemove={() => remove(i)}
          onMove={(d) => move(i, d)}
        />
      ))}
      <button
        type="button"
        onClick={() => onChange([...turns, emptyTurn()])}
        className="btn-ghost w-full justify-center text-[12.5px]"
      >
        + Add turn
      </button>
    </div>
  );
}

function TurnRow({
  index,
  turn,
  total,
  toolsEnabled,
  idPrefix,
  onPatch,
  onRemove,
  onMove,
}: {
  index: number;
  turn: ScenarioTurn;
  total: number;
  toolsEnabled: boolean;
  idPrefix: string;
  onPatch: (patch: Partial<ScenarioTurn>) => void;
  onRemove: () => void;
  onMove: (delta: number) => void;
}) {
  const has = Boolean(turn.expect || turn.tools.length);
  const [open, setOpen] = useState(has);

  return (
    <div className="rounded-lg border border-line bg-ink-900/40 p-3">
      <div className="flex items-start gap-2.5">
        <span className="mt-2 w-6 shrink-0 text-center font-mono text-[11px] text-fg-faint">
          {index + 1}
        </span>
        <textarea
          value={turn.message}
          onChange={(e) => onPatch({ message: e.target.value })}
          rows={Math.min(6, Math.max(1, turn.message.split("\n").length))}
          placeholder="What the user says…"
          aria-label={`Turn ${index + 1} user message`}
          className={`${FIELD} resize-y leading-relaxed`}
        />
        <div className="flex shrink-0 flex-col items-center gap-0.5">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={index === 0}
            aria-label={`Move turn ${index + 1} up`}
            className="text-fg-faint transition-colors hover:text-fg disabled:opacity-25"
          >
            <IconChevron className="h-3.5 w-3.5 -rotate-90" />
          </button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={index === total - 1}
            aria-label={`Move turn ${index + 1} down`}
            className="text-fg-faint transition-colors hover:text-fg disabled:opacity-25"
          >
            <IconChevron className="h-3.5 w-3.5 rotate-90" />
          </button>
          <button
            type="button"
            onClick={onRemove}
            disabled={total === 1}
            aria-label={`Remove turn ${index + 1}`}
            className="mt-0.5 text-fg-faint transition-colors hover:text-fail disabled:opacity-25"
          >
            <IconX className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="mt-2 pl-8">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className={clsx(
            "font-mono text-[11px] transition-colors",
            has ? "text-signal" : "text-fg-faint hover:text-fg-muted",
          )}
        >
          {open ? "− " : "+ "}
          {has ? "expectations set" : "add expectation"}
        </button>

        {open && (
          <div className="mt-2 space-y-2 border-l border-line pl-3">
            <div>
              <label className={LABEL} htmlFor={`${idPrefix}-exp-${index}`}>
                The reply should…
              </label>
              <input
                id={`${idPrefix}-exp-${index}`}
                value={turn.expect}
                onChange={(e) => onPatch({ expect: e.target.value })}
                placeholder="apologise and offer a refund"
                className={`${FIELD} mt-1`}
              />
            </div>
            {toolsEnabled && (
              <div>
                <label className={LABEL} htmlFor={`${idPrefix}-tools-${index}`}>
                  Tools it must call <span className="text-fg-faint">(comma-separated)</span>
                </label>
                <input
                  id={`${idPrefix}-tools-${index}`}
                  value={turn.tools.join(", ")}
                  onChange={(e) =>
                    onPatch({
                      tools: e.target.value
                        .split(",")
                        .map((t) => t.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="issue_refund, lookup_order"
                  className={`${FIELD} mt-1`}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
