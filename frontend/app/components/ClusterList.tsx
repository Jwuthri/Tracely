"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { FailureCluster } from "../lib/api";
import { IconChevron } from "./icons";
import { RowLink } from "./RowLink";
import { SelectBox } from "./SelectBox";
import { TimeAgo } from "./TimeAgo";
import { Badge } from "./ui";
import { ClusterMeter, TaxonomyChip, clusterTone } from "./ClusterMeter";

const GRID = "grid grid-cols-[32px_64px_1fr_120px_120px_28px] items-center gap-3";

function clusterVariant(s: string): "warn" | "ok" | "neutral" {
  if (s === "OPEN") return "warn";
  if (s === "PROMOTED") return "ok";
  return "neutral";
}

/** The failure-cluster rows + multi-select delete. Clusters are derived from traces, so this is
 * pruning: noise, and issues left orphaned when their traces were deleted. */
export function ClusterList({ clusters }: { clusters: FailureCluster[] }) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const allSelected = clusters.length > 0 && selected.size >= clusters.length;
  // meters are relative to the biggest cluster on this page — the point is "which of these do I
  // pick up first", not an absolute share of every failure in the project.
  const max = Math.max(1, ...clusters.map((c) => c.count));

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  async function deleteSelected() {
    const ids = [...selected];
    if (!ids.length) return;
    if (!window.confirm(`Delete ${ids.length} cluster${ids.length === 1 ? "" : "s"}? Analyze re-forms any issue whose failing traces still exist.`)) return;
    setDeleting(true);
    setError("");
    try {
      const r = await fetch("/api/clusters", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cluster_ids: ids }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "delete failed");
      setSelected(new Set());
      router.refresh(); // the page is a Server Component — re-read the list from the server
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete failed");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="reveal card overflow-hidden" style={{ animationDelay: "80ms" }}>
      <div className={`${GRID} border-b border-line bg-ink-900/50 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-wider text-fg-faint`}>
        {clusters.length > 0 ? (
          <SelectBox
            checked={allSelected}
            indeterminate={selected.size > 0 && !allSelected}
            onChange={() => setSelected(allSelected ? new Set() : new Set(clusters.map((c) => c.id)))}
            label={allSelected ? "Clear selection" : "Select all clusters"}
          />
        ) : (
          <span />
        )}
        <span className="text-right">Seen</span>
        <span>Failure</span>
        <span>Status</span>
        <span className="text-right">Last</span>
        <span />
      </div>

      {selected.size > 0 && (
        <div className="flex items-center gap-3 border-b border-line bg-ink-900/30 px-4 py-2">
          <span className="font-mono text-[11px] text-fg-faint">{selected.size} selected</span>
          <button
            onClick={() => void deleteSelected()}
            disabled={deleting}
            className="rounded-lg border border-fail/40 bg-fail/10 px-3 py-1.5 text-xs font-medium text-fail transition-colors hover:bg-fail/20 disabled:opacity-50"
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="rounded-lg px-2 py-1.5 text-xs text-fg-faint transition-colors hover:text-fg"
          >
            Clear
          </button>
          {error && <span className="truncate text-[12px] text-fail">{error}</span>}
        </div>
      )}

      {clusters.length === 0 ? (
        <div className="px-4 py-14 text-center text-[13px] text-fg-faint">
          No clusters yet — they form automatically as failures are detected.
        </div>
      ) : (
        clusters.map((c) => (
          <RowLink
            key={c.id}
            href={`/clusters/${c.id}`}
            className={`${GRID} group border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-hilite/[0.025]`}
          >
            <SelectBox checked={selected.has(c.id)} onChange={() => toggle(c.id)} label={`Select "${c.label}"`} />
            <span className={`text-right font-display text-[20px] font-extrabold tabular-nums ${clusterTone(c.taxonomy).text}`}>
              {c.count}
            </span>
            <span className="flex min-w-0 flex-col gap-1.5">
              <span className="truncate text-[13.5px] text-fg">{c.label}</span>
              <span className="flex items-center gap-2.5">
                <TaxonomyChip taxonomy={c.taxonomy} tone={clusterTone(c.taxonomy)} />
                <ClusterMeter value={c.count} max={max} tone={clusterTone(c.taxonomy)} className="w-full max-w-[220px]" />
              </span>
            </span>
            <span>
              <Badge variant={clusterVariant(c.status)} dot>
                {c.status}
              </Badge>
            </span>
            <TimeAgo ts={c.last_seen_at} className="text-right font-mono text-[11.5px] text-fg-faint" />
            <IconChevron className="h-4 w-4 justify-self-end text-fg-faint transition-colors group-hover:text-signal" />
          </RowLink>
        ))
      )}
    </div>
  );
}
