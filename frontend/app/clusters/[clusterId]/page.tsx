import { getCluster } from "../../lib/api";
import { ClusterActions } from "../../components/ClusterActions";
import { CopyId } from "../../components/CopyId";
import { Badge } from "../../components/ui";
import { IconArrowLeft } from "../../components/icons";

function clusterVariant(s: string): "warn" | "ok" | "neutral" {
  if (s === "OPEN") return "warn";
  if (s === "PROMOTED") return "ok";
  return "neutral";
}

export default async function ClusterPage({ params }: { params: Promise<{ clusterId: string }> }) {
  const { clusterId } = await params;
  const c = await getCluster(clusterId);
  if (!c) {
    return (
      <div className="card p-10 text-center">
        <p className="text-fg-muted">Cluster not found.</p>
        <a href="/clusters" className="mt-3 inline-block text-signal">← failure clusters</a>
      </div>
    );
  }
  const members = c.members ?? [];

  return (
    <div className="space-y-6">
      <header className="reveal">
        <a href="/clusters" className="inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors hover:text-signal">
          <IconArrowLeft className="h-4 w-4" /> Failure clusters
        </a>
      </header>

      <div className="reveal card flex flex-wrap items-center justify-between gap-5 border-fail/30 bg-fail/[0.04] p-5">
        <div className="flex items-center gap-4">
          <div className="grid h-12 w-14 place-items-center rounded-xl border border-fail/40 bg-fail/10">
            <span className="font-display text-[24px] font-extrabold tabular-nums text-fail">{c.count}</span>
          </div>
          <div>
            <div className="font-display text-[20px] font-extrabold leading-tight text-fg">{c.label}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2.5 font-mono text-[11.5px] text-fg-faint">
              <span>{c.taxonomy}</span>·<span>{c.agent}</span>·
              <Badge variant={clusterVariant(c.status)} dot>{c.status}</Badge>
              {c.severity && (
                <Badge variant={c.severity === "high" ? "fail" : c.severity === "medium" ? "warn" : "neutral"}>
                  {c.severity}
                </Badge>
              )}
            </div>
          </div>
        </div>
        <ClusterActions clusterId={c.id} status={c.status} />
      </div>

      {c.candidate_case_id && (
        <a
          href={`/cases/${c.candidate_case_id}`}
          className="reveal block rounded-lg border border-ok/30 bg-ok/[0.04] px-4 py-3 text-[13px] text-ok transition-colors hover:bg-ok/[0.08]"
        >
          → Promoted to a regression case
        </a>
      )}

      {c.description && (
        <section className="reveal card overflow-hidden" style={{ animationDelay: "90ms" }}>
          <div className="border-b border-line px-4 py-3 text-[13px] font-semibold text-fg">Analysis</div>
          <p className="px-4 py-3.5 text-[13.5px] leading-relaxed text-fg-muted">{c.description}</p>
        </section>
      )}
      {c.proposed_fix && (
        <section className="reveal card overflow-hidden" style={{ animationDelay: "110ms" }}>
          <div className="border-b border-line px-4 py-3 text-[13px] font-semibold text-signal">Proposed fix</div>
          <p className="px-4 py-3.5 text-[13.5px] leading-relaxed text-fg-muted">{c.proposed_fix}</p>
        </section>
      )}
      {c.signature && (
        <section className="reveal card overflow-hidden" style={{ animationDelay: "130ms" }}>
          <div className="border-b border-line px-4 py-3 text-[13px] font-semibold text-fg">Signature</div>
          <pre className="overflow-auto px-4 py-3 font-mono text-[11.5px] leading-relaxed text-fg-muted">
            {c.signature}
          </pre>
        </section>
      )}

      <section className="reveal card overflow-hidden" style={{ animationDelay: "140ms" }}>
        <div className="border-b border-line px-4 py-3 text-[13px] font-semibold text-fg">
          Members <span className="font-mono text-[11px] text-fg-faint">({members.length})</span>
        </div>
        {members.map((m, i) => (
          <div key={i} className="border-b border-line/50 px-4 py-2.5 text-[12.5px] last:border-0">
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2.5">
                <a href={`/traces/${m.trace_id}`} className="font-mono text-[12px] text-signal hover:underline">
                  {m.trace_id.slice(0, 18)}…
                </a>
                {m.is_medoid && <Badge variant="signal">representative</Badge>}
              </span>
              <CopyId value={m.trace_id} label="trace id" />
            </div>
            {m.summary && <p className="mt-1.5 text-[12px] leading-relaxed text-fg-muted">{m.summary}</p>}
          </div>
        ))}
      </section>
    </div>
  );
}
