"use client";

import clsx from "clsx";
import { useState } from "react";
import { IconCheck, IconCopy } from "./icons";

export function CodeBlock({ code, action = "Copy" }: { code: string; action?: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard?.writeText(code).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1100);
  }
  return (
    <div className="relative">
      <pre className="overflow-auto rounded-lg border border-line bg-ink-900 p-3 pr-24 font-mono text-[11.5px] leading-relaxed text-fg-muted">
        {code}
      </pre>
      <button
        onClick={copy}
        className={clsx(
          "absolute right-2 top-2 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors",
          copied ? "border-ok/40 bg-ok/10 text-ok" : "border-signal/40 bg-signal/10 text-signal hover:bg-signal/20",
        )}
      >
        {copied ? <IconCheck className="h-3.5 w-3.5" /> : <IconCopy className="h-3.5 w-3.5" />}
        {copied ? "copied" : action}
      </button>
    </div>
  );
}
