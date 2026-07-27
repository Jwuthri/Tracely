import { getClusters } from "@/app/lib/api";
import { Badge } from "@/app/components/ui";
import { ClusterList } from "@/app/components/ClusterList";
import { RebuildButton } from "@/app/components/RebuildButton";

export default async function ClustersPage() {
  const clusters = await getClusters();
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
          <Badge variant="warn">{open} open</Badge>
          <RebuildButton />
        </div>
      </header>

      {/* rows + multi-select delete (client) */}
      <ClusterList clusters={clusters} />
    </div>
  );
}
