import type { ReactNode } from "react";

// Lightweight JSON syntax highlighter (shared by the trace table, the timeline span panel, and the
// attributes list) — object keys, string values, numbers, and booleans/null each get a distinct
// color. Operates on already-pretty-printed text so whitespace/indentation is preserved verbatim.
export function HighlightedJson({ text }: { text: string }) {
  const out: ReactNode[] = [];
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined && m[2] !== undefined) {
      // "key":  -> key (fuchsia) + colon (slate)
      out.push(<span key={i++} className="text-fuchsia-400">{m[1]}</span>);
      out.push(<span key={i++} className="text-slate-500">{m[2]}</span>);
    } else if (m[1] !== undefined) {
      out.push(<span key={i++} className="text-cyan-300">{m[1]}</span>); // string value
    } else if (m[3] !== undefined) {
      out.push(<span key={i++} className="text-violet-400">{m[3]}</span>); // true/false/null
    } else if (m[4] !== undefined) {
      out.push(<span key={i++} className="text-amber-300">{m[4]}</span>); // number
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

// Pretty-print any value to a highlighted string. Strings that are themselves JSON are parsed and
// re-indented; everything else is JSON.stringified. Returns null for empty/whitespace strings.
export function prettyJson(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string") {
    const t = value.trim();
    if (t === "") return null;
    if (t.startsWith("{") || t.startsWith("[")) {
      try {
        return JSON.stringify(JSON.parse(t), null, 2);
      } catch {
        return value; // not valid JSON — show as-is
      }
    }
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
