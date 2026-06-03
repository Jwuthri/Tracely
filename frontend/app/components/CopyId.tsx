"use client";

import clsx from "clsx";
import { useState } from "react";
import { IconCheck, IconCopy } from "./icons";

/** Compact "[ID]" copy link — hides the value, copies the full id on click. */
export function CopyId({
  value,
  label,
  text = "ID",
  className,
}: {
  value: string;
  label?: string;
  text?: string;
  chars?: number; // accepted for back-compat, unused
  full?: boolean; // accepted for back-compat, unused
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* ignore */
      }
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1100);
  }

  return (
    <button
      type="button"
      onClick={copy}
      title={`Copy ${label ?? "id"}: ${value}`}
      className={clsx(
        "group/c inline-flex items-center gap-1 font-mono text-[11px] font-medium transition-colors",
        copied ? "text-ok" : "text-fg-faint hover:text-signal",
        className,
      )}
    >
      <span>{copied ? "copied" : `[${text}]`}</span>
      {copied ? (
        <IconCheck className="h-3 w-3" />
      ) : (
        <IconCopy className="h-3 w-3 opacity-60 transition-opacity group-hover/c:opacity-100" />
      )}
    </button>
  );
}
