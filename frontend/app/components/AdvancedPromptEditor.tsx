"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { EvaluatorLevel } from "../lib/evaluators";
import {
  VARIABLE_RE,
  catalogLevel,
  getVariable,
  getVariablesForLevel,
} from "../lib/templateVariables";
import { VariableAutocomplete, type AutocompleteItem } from "./VariableAutocomplete";

// The advanced prompt editor: a transparent <textarea> over a synced highlight overlay (so
// @VARIABLE tokens glow emerald), with `@`/`.`-triggered autocomplete anchored at the caret.

type AcItem = AutocompleteItem & { insert: string };

type AcState = {
  open: boolean;
  items: AcItem[];
  selected: number;
  pos: { top: number; left: number };
  start: number; // index in the value where the inserted token begins
  prefix: string; // "@" for top-level vars, "" for nested props
};

const CLOSED: AcState = { open: false, items: [], selected: 0, pos: { top: 0, left: 0 }, start: 0, prefix: "@" };

const NESTED_RE = /@([A-Z_]+)\.([a-z_]*)$/;
const TOP_RE = /@([A-Z_]*)$/;

// Properties the caret-measuring mirror must mirror from the textarea for char-accurate metrics.
const MIRROR_PROPS = [
  "boxSizing", "width", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
  "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
  "fontStyle", "fontVariant", "fontWeight", "fontStretch", "fontSize", "fontFamily",
  "lineHeight", "letterSpacing", "wordSpacing", "textTransform", "textIndent", "whiteSpace",
  "wordWrap", "tabSize",
] as const;

function caretCoords(ta: HTMLTextAreaElement, text: string, position: number): { top: number; left: number } {
  const div = document.createElement("div");
  const computed = getComputedStyle(ta);
  div.style.position = "absolute";
  div.style.visibility = "hidden";
  div.style.whiteSpace = "pre-wrap";
  div.style.wordWrap = "break-word";
  div.style.overflow = "hidden";
  for (const p of MIRROR_PROPS) div.style[p as never] = computed[p as never];
  div.style.width = computed.width;
  div.textContent = text.slice(0, position);
  const marker = document.createElement("span");
  marker.textContent = text.slice(position) || ".";
  div.appendChild(marker);
  document.body.appendChild(div);
  const top = marker.offsetTop + parseFloat(computed.borderTopWidth || "0");
  const left = marker.offsetLeft + parseFloat(computed.borderLeftWidth || "0");
  document.body.removeChild(div);
  return { top, left };
}

function renderHighlighted(text: string): ReactNode[] {
  const re = new RegExp(VARIABLE_RE.source, "g");
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<span key={key++}>{text.slice(last, m.index)}</span>);
    out.push(<span key={key++} className="font-semibold text-emerald-400">{m[0]}</span>);
    last = m.index + m[0].length;
  }
  // trailing text + a ZWSP so the overlay keeps the final (possibly empty) line aligned
  out.push(<span key={key++}>{text.slice(last)}{"​"}</span>);
  return out;
}

export function AdvancedPromptEditor({
  value,
  onChange,
  level,
  sequential = false,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  level: EvaluatorLevel;
  sequential?: boolean;
  placeholder?: string;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [ac, setAc] = useState<AcState>(CLOSED);

  const close = useCallback(() => setAc((s) => (s.open ? CLOSED : s)), []);

  const levelCount = getVariablesForLevel(level, sequential).length;

  const recompute = useCallback(
    (text: string, caret: number) => {
      const ta = taRef.current;
      if (!ta) return;
      const before = text.slice(0, caret);

      // nested: @PARENT.<query>  → the parent's properties
      const nested = NESTED_RE.exec(before);
      if (nested) {
        const parent = getVariable(nested[1]);
        if (parent?.type === "object" && parent.props) {
          const q = nested[2].toLowerCase();
          const items: AcItem[] = parent.props
            .filter((p) => p.name.toLowerCase().startsWith(q))
            .map((p) => ({ name: p.name, description: p.description, insert: p.name, isObject: false }));
          if (items.length) {
            setAc({ open: true, items, selected: 0, pos: caretBelow(ta, text, caret), start: caret - nested[2].length, prefix: "" });
            return;
          }
        }
        close();
        return;
      }

      // top-level: @<query>  → the level's variables
      const top = TOP_RE.exec(before);
      if (top) {
        const q = top[1].toUpperCase();
        const items: AcItem[] = getVariablesForLevel(level, sequential)
          .filter((v) => v.name.startsWith(q))
          .map((v) => ({
            name: v.name,
            description: v.description,
            isObject: v.type === "object",
            insert: v.type === "object" ? `@${v.name}.` : `@${v.name}`,
          }));
        if (items.length) {
          setAc({ open: true, items, selected: 0, pos: caretBelow(ta, text, caret), start: caret - top[0].length, prefix: "@" });
          return;
        }
      }
      close();
    },
    [level, sequential, close],
  );

  function caretBelow(ta: HTMLTextAreaElement, text: string, caret: number) {
    const c = caretCoords(ta, text, caret);
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 18;
    return { top: c.top - ta.scrollTop + lh + 2, left: Math.min(c.left - ta.scrollLeft, ta.clientWidth - 40) };
  }

  const insert = useCallback(
    (index: number) => {
      const ta = taRef.current;
      if (!ta) return;
      const it = ac.items[index];
      if (!it) return;
      const caret = ta.selectionStart;
      const next = value.slice(0, ac.start) + it.insert + value.slice(caret);
      const newCaret = ac.start + it.insert.length;
      onChange(next);
      close();
      requestAnimationFrame(() => {
        const t = taRef.current;
        if (!t) return;
        t.focus();
        t.setSelectionRange(newCaret, newCaret);
        // an object var inserts "@NAME." — immediately offer its properties
        if (it.insert.endsWith(".")) recompute(next, newCaret);
      });
    },
    [ac, value, onChange, close, recompute],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!ac.open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setAc((s) => ({ ...s, selected: (s.selected + 1) % s.items.length }));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setAc((s) => ({ ...s, selected: (s.selected - 1 + s.items.length) % s.items.length }));
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      insert(ac.selected);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };

  // keep the highlight overlay scrolled in lock-step with the textarea
  const syncScroll = () => {
    const ta = taRef.current;
    const ov = overlayRef.current;
    if (ta && ov) {
      ov.scrollTop = ta.scrollTop;
      ov.scrollLeft = ta.scrollLeft;
    }
    if (ac.open) close();
  };

  useEffect(() => {
    return () => { /* unmount: nothing to clean (mirror is transient) */ };
  }, []);

  return (
    <div className="relative">
      <div className="relative rounded-lg border border-line bg-ink-900/60 transition-colors focus-within:border-signal/40">
        <div
          ref={overlayRef}
          aria-hidden
          className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words px-3 py-2 font-mono text-[12.5px] leading-relaxed text-fg"
        >
          {renderHighlighted(value)}
        </div>
        <textarea
          ref={taRef}
          value={value}
          spellCheck={false}
          placeholder={placeholder}
          onChange={(e) => {
            onChange(e.target.value);
            recompute(e.target.value, e.target.selectionStart);
          }}
          onKeyDown={onKeyDown}
          onScroll={syncScroll}
          onBlur={close}
          onClick={(e) => recompute(value, e.currentTarget.selectionStart)}
          className="relative block h-44 w-full resize-none bg-transparent px-3 py-2 font-mono text-[12.5px] leading-relaxed text-transparent caret-white placeholder:text-fg-faint/60 outline-none"
        />
      </div>
      {ac.open && (
        <VariableAutocomplete
          items={ac.items}
          selected={ac.selected}
          position={ac.pos}
          prefix={ac.prefix}
          onSelect={insert}
          onHover={(i) => setAc((s) => ({ ...s, selected: i }))}
          onClose={close}
        />
      )}
      <div className="mt-1.5 flex items-center justify-between text-[10.5px] text-fg-faint">
        <span>
          Type <span className="font-mono text-emerald-400">@</span> to insert a variable
        </span>
        <span>
          Available variables: {levelCount} · Level: {catalogLevel(level)}
        </span>
      </div>
    </div>
  );
}
