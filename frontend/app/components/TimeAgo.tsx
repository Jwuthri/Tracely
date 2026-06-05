"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

/** Relative time from a timestamp; pass `now` only in tests or effects. */
export function formatTimeAgo(ts: string | null | undefined, now = Date.now()): string {
  if (!ts) return "";
  const d = new Date(ts).getTime();
  if (Number.isNaN(d)) return "";
  const s = Math.max(0, (now - d) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Relative timestamp safe for SSR — empty on server/first paint, updates after mount. */
export function TimeAgo({
  ts,
  className,
}: {
  ts: string | null | undefined;
  className?: string;
}) {
  const [label, setLabel] = useState("");

  useEffect(() => {
    const tick = () => setLabel(formatTimeAgo(ts));
    tick();
    const id = window.setInterval(tick, 30_000);
    return () => window.clearInterval(id);
  }, [ts]);

  return (
    <span className={clsx(className)} suppressHydrationWarning>
      {label}
    </span>
  );
}
