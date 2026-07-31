import { getClusters } from "@/app/lib/api";
import { Badge } from "@/app/components/ui";
import { ClusterList } from "@/app/components/ClusterList";
import { RebuildButton } from "@/app/components/RebuildButton";

export default async function ClustersPage({
  searchParams,
}: {
  searchParams: Promise<{ min_size?: string }>;
}) {
  const raw = Number((await searchParams).min_size);
  // ponytail: plain GET form -> URL -> server re-fetch. No client state, back button works.
  const minSize = Number.isFinite(raw) && raw >= 2 ? Math.floor(raw) : undefined;
  const clusters = await getClusters(minSize);
  const open = clusters.filter((c) => c.status === "OPEN").length;
  return (
    <div className="space-y-6">
      <header className="reveal flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">Failure clusters</h1>
          <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
            Auto-detected failures grouped into issues — run <span className="text-fg">Analyze</span> to
            cluster with embeddings + LLM agents, then promote an issue into a regression test.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <form className="flex items-center gap-2 text-[13px] text-fg-muted">
            <label htmlFor="min_size">Min occurrences</label>
            <input
              id="min_size"
              name="min_size"
              type="number"
              min={2}
              step={1}
              defaultValue={minSize ?? 5}
              className="w-16 rounded-md border border-line bg-ink-900 px-2 py-1 text-[13px] text-fg"
            />
            <button type="submit" className="btn-ghost">
              Apply
            </button>
          </form>
          <Badge variant="warn">{open} open</Badge>
          <RebuildButton />
        </div>
      </header>

      {/* rows + multi-select delete (client) */}
      <ClusterList clusters={clusters} />
    </div>
  );
}
