import { getClusters } from "../lib/api";
import { Badge } from "../components/ui";
import { RowLink } from "../components/RowLink";
import { RebuildButton } from "../components/RebuildButton";
import { IconChevron } from "../components/icons";

function clusterVariant(s: string): "warn" | "ok" | "neutral" {
  if (s === "OPEN") return "warn";
  if (s === "PROMOTED") return "ok";
  return "neutral";
}

function ago(ts: string | null): string {
  if (!ts) return "";
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

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

      <div className="reveal card overflow-hidden" style={{ animationDelay: "80ms" }}>
        <div className="grid grid-cols-[64px_1fr_120px_120px_28px] items-center gap-3 border-b border-line bg-ink-900/50 px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-wider text-fg-faint">
          <span className="text-right">Seen</span>
          <span>Failure</span>
          <span>Status</span>
          <span className="text-right">Last</span>
          <span />
        </div>
        {clusters.length === 0 ? (
          <div className="px-4 py-14 text-center text-[13px] text-fg-faint">
            No clusters yet — they form automatically as failures are detected.
          </div>
        ) : (
          clusters.map((c) => (
            <RowLink
              key={c.id}
              href={`/clusters/${c.id}`}
              className="group grid grid-cols-[64px_1fr_120px_120px_28px] items-center gap-3 border-b border-line/50 px-4 py-3 transition-colors last:border-0 hover:bg-white/[0.025]"
            >
              <span className="text-right font-display text-[20px] font-extrabold tabular-nums text-fail">
                {c.count}
              </span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[13.5px] text-fg">{c.label}</span>
                <span className="font-mono text-[10.5px] text-fg-faint">{c.taxonomy}</span>
              </span>
              <span>
                <Badge variant={clusterVariant(c.status)} dot>
                  {c.status}
                </Badge>
              </span>
              <span className="text-right font-mono text-[11.5px] text-fg-faint">{ago(c.last_seen_at)}</span>
              <IconChevron className="h-4 w-4 justify-self-end text-fg-faint transition-colors group-hover:text-signal" />
            </RowLink>
          ))
        )}
      </div>
    </div>
  );
}
