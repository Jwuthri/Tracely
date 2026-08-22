"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconX } from "./icons";

/** "Don't show me this one again." The endpoint and the IGNORED status already exist
 * (clusters.py, and the Ignore button on the cluster detail page) — this just puts them where
 * you actually notice the noise. The dashboard lists OPEN only, so the row simply goes away. */
export function IgnoreCluster({ clusterId }: { clusterId: string }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");

  async function ignore(e: React.MouseEvent) {
    e.stopPropagation(); // the whole row is a link
    e.preventDefault();
    setState("busy");
    try {
      const r = await fetch("/api/cluster", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ clusterId, action: "ignore" }),
      });
      if (!r.ok) throw new Error();
      router.refresh(); // server component — re-read the list
    } catch {
      setState("failed"); // silent failure here would read as "it worked"
    }
  }

  return (
    <button
      onClick={ignore}
      disabled={state === "busy"}
      title={state === "failed" ? "Couldn't ignore — try again" : "Ignore: stop showing this cluster"}
      aria-label="Ignore this cluster"
      className={`shrink-0 rounded p-1 opacity-0 transition-all focus:opacity-100 group-hover:opacity-100 ${
        state === "failed" ? "text-fail opacity-100" : "text-fg-faint hover:bg-hilite/[0.06] hover:text-fg"
      }`}
    >
      <IconX className="h-3.5 w-3.5" />
    </button>
  );
}
