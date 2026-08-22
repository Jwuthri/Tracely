"use client";

import clsx from "clsx";
import { useLayoutEffect, useRef, useState } from "react";
import { VARIABLE_DRAG_MIME, splitVariableTokens, tokenDeletionRange } from "@/app/lib/ruleFlow";
import { LABEL } from "./tone";

/** Template fields: a draggable variable chip, and the two inputs that accept one.
 *
 *  There is no rich-text editor here. A native `<input>`/`<textarea>` is rendered with transparent
 *  text and a visible caret, layered over an `aria-hidden` mirror that paints the same string with
 *  `{{ token }}` runs highlighted. Cheap, accessible, and it never fights the browser's own
 *  editing — the value in state stays plain text. */

const chipClass =
  "inline-flex max-w-full cursor-grab items-center gap-1 rounded-md border border-signal/30 bg-signal/10 px-1.5 py-0.5 font-mono text-[10.5px] text-signal transition-colors hover:border-signal/60 active:cursor-grabbing";

export function VariableChip({
  label,
  token,
  title,
}: {
  label: string;
  token: string;
  title?: string;
}) {
  return (
    <span
      draggable
      title={title ?? token}
      onDragStart={(e) => {
        e.dataTransfer.setData(VARIABLE_DRAG_MIME, token);
        e.dataTransfer.setData("text/plain", token); // fallback for drop targets we don't own
        e.dataTransfer.effectAllowed = "copy";
      }}
      className={chipClass}
    >
      <span aria-hidden className="opacity-50">
        ⠿
      </span>
      <span className="truncate">{label}</span>
    </span>
  );
}

/** Insert `token` at the caret and put the caret after it — one frame later, because React has to
 *  commit the new value before a selection into it means anything. */
function insertToken(
  el: HTMLInputElement | HTMLTextAreaElement,
  value: string,
  token: string,
  onChange: (next: string) => void,
) {
  const start = el.selectionStart ?? value.length;
  const end = el.selectionEnd ?? value.length;
  onChange(`${value.slice(0, start)}${token}${value.slice(end)}`);
  const pos = start + token.length;
  requestAnimationFrame(() => {
    el.focus();
    el.setSelectionRange(pos, pos);
  });
}

function handleTokenKey(
  e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
  value: string,
  onChange: (next: string) => void,
) {
  if (e.key !== "Backspace" && e.key !== "Delete") return;
  const el = e.currentTarget;
  const start = el.selectionStart ?? 0;
  if (start !== (el.selectionEnd ?? 0)) return; // a real selection: let the browser handle it
  const range = tokenDeletionRange(value, start, e.key);
  if (!range) return;
  e.preventDefault();
  const [s, en] = range;
  onChange(value.slice(0, s) + value.slice(en));
  requestAnimationFrame(() => {
    el.focus();
    el.setSelectionRange(s, s);
  });
}

function Mirror({ value, wrap }: { value: string; wrap: boolean }) {
  return (
    <div
      aria-hidden
      className={clsx(
        "pointer-events-none absolute inset-0 overflow-hidden px-2.5 font-mono text-[12px] text-fg",
        wrap ? "whitespace-pre-wrap break-words py-2 leading-relaxed" : "flex items-center whitespace-pre",
      )}
    >
      <span>
        {splitVariableTokens(value).map((seg, i) =>
          seg.kind === "token" ? (
            <span key={i} className="rounded-[3px] bg-signal/20 text-signal">
              {seg.value}
            </span>
          ) : (
            <span key={i}>{seg.value}</span>
          ),
        )}
        {value.endsWith("\n") ? "​" : null}
      </span>
    </div>
  );
}

const shellClass = (dragOver: boolean) =>
  clsx(
    "relative rounded-lg border bg-ink-700 transition-colors",
    dragOver ? "border-signal ring-2 ring-signal/20" : "border-line hover:border-line-bright",
  );

export function VariableInput({
  id,
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const [dragOver, setDragOver] = useState(false);

  // The mirror has to scroll with the input or a long value shows the wrong part of itself.
  const syncScroll = () => {
    if (ref.current && mirrorRef.current) mirrorRef.current.scrollLeft = ref.current.scrollLeft;
  };
  useLayoutEffect(syncScroll);

  return (
    <div className="space-y-1">
      <label htmlFor={id} className={LABEL}>
        {label}
      </label>
      <div
        className={shellClass(dragOver)}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const token = e.dataTransfer.getData(VARIABLE_DRAG_MIME) || e.dataTransfer.getData("text/plain");
          if (token && ref.current) insertToken(ref.current, value, token, onChange);
        }}
      >
        <div ref={mirrorRef} className="absolute inset-0">
          <Mirror value={value} wrap={false} />
        </div>
        <input
          ref={ref}
          id={id}
          spellCheck={false}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => handleTokenKey(e, value, onChange)}
          onScroll={syncScroll}
          className="relative h-9 w-full bg-transparent px-2.5 font-mono text-[12px] text-transparent caret-fg outline-none placeholder:text-fg-faint selection:bg-signal/20"
        />
      </div>
      {hint ? <p className="text-[11px] text-fg-faint">{hint}</p> : null}
    </div>
  );
}

export function VariableTextarea({
  id,
  label,
  value,
  onChange,
  rows = 4,
  hint,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  rows?: number;
  hint?: string;
  placeholder?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [dragOver, setDragOver] = useState(false);

  // Auto-grow: the mirror is absolutely positioned, so the textarea's own height is what sizes
  // the box, and a scrollbar inside it would slide the highlight out of alignment.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <div className="space-y-1">
      <label htmlFor={id} className={LABEL}>
        {label}
      </label>
      <div
        className={shellClass(dragOver)}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const token = e.dataTransfer.getData(VARIABLE_DRAG_MIME) || e.dataTransfer.getData("text/plain");
          if (token && ref.current) insertToken(ref.current, value, token, onChange);
        }}
      >
        <Mirror value={value} wrap />
        <textarea
          ref={ref}
          id={id}
          rows={rows}
          spellCheck={false}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => handleTokenKey(e, value, onChange)}
          className="relative block min-h-[80px] w-full resize-none overflow-hidden bg-transparent px-2.5 py-2 font-mono text-[12px] leading-relaxed text-transparent caret-fg outline-none placeholder:text-fg-faint selection:bg-signal/20"
        />
      </div>
      {hint ? <p className="text-[11px] text-fg-faint">{hint}</p> : null}
    </div>
  );
}
