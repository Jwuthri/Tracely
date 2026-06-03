import { getCase } from "../../lib/api";
import { ReplayControls } from "../../components/ReplayControls";
import { Badge, statusVariant, TypeChip, verdictVariant } from "../../components/ui";
import { IconArrowLeft } from "../../components/icons";

export default async function CasePage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params;
  const c = await getCase(caseId);
  if (!c) {
    return (
      <div className="card p-10 text-center">
        <p className="text-fg-muted">Case not found.</p>
        <a href="/cases" className="mt-3 inline-block text-signal">← cases</a>
      </div>
    );
  }
  const steps = c.reference_trajectory?.steps ?? [];
  const requiredTools = (c.assertions?.required_tools as string[]) ?? [];
  const replays = c.replays ?? [];

  return (
    <div className="space-y-6">
      <header className="reveal space-y-4">
        <a href="/cases" className="inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors hover:text-signal">
          <IconArrowLeft className="h-4 w-4" /> Regression cases
        </a>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-display text-[24px] font-extrabold tracking-tight">{c.title || "case"}</h1>
          <Badge variant={statusVariant(c.status)} dot>{c.status}</Badge>
          {c.fail_to_pass_validated && <Badge variant="signal">fail → pass validated</Badge>}
        </div>
      </header>

      {/* meta strip */}
      <div className="reveal card grid grid-cols-2 divide-x divide-line/60 sm:grid-cols-4" style={{ animationDelay: "60ms" }}>
        <Meta k="Level" v={c.level} />
        <Meta k="Match mode" v={c.match_mode} />
        <Meta k="Origin" v={c.origin} />
        <Meta k="Source" v={`${c.source_trace_id.slice(0, 10)}…`} href={`/traces/${c.source_trace_id}`} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* assertions */}
        <section className="reveal card overflow-hidden" style={{ animationDelay: "120ms" }}>
          <Head>Assertions</Head>
          <div className="space-y-3 p-4 font-mono text-[12.5px]">
            <Assertion k="no_error" v={String(c.assertions?.no_error)} ok={c.assertions?.no_error === true} />
            <div>
              <div className="text-fg-faint">required_tools</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {requiredTools.length ? (
                  requiredTools.map((t, i) => (
                    <span key={i} className="rounded-md border border-line bg-ink-900 px-2 py-0.5 text-[11.5px] text-t_tool">
                      {t}
                    </span>
                  ))
                ) : (
                  <span className="text-fg-faint">none</span>
                )}
              </div>
            </div>
            <Assertion k="match_mode" v={String(c.assertions?.match_mode)} />
          </div>
        </section>

        {/* reference trajectory */}
        <section className="reveal card overflow-hidden" style={{ animationDelay: "160ms" }}>
          <Head>Reference trajectory</Head>
          <div className="p-2">
            {steps.map((s, i) => (
              <div
                key={i}
                className="flex items-center gap-3 rounded-lg px-3 py-2"
                style={{ paddingLeft: 12 + (s.kind === "agent" ? 0 : 18) }}
              >
                <TypeChip type={s.kind === "llm" ? "GENERATION" : s.kind.toUpperCase()} />
                <span className={`font-mono text-[12.5px] ${s.level === "ERROR" ? "text-fail" : "text-fg"}`}>
                  {s.name}
                </span>
                {s.level === "ERROR" && <span className="font-mono text-[11px] text-fail">✕ error</span>}
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* replay */}
      <section className="reveal card overflow-hidden" style={{ animationDelay: "200ms" }}>
        <Head>Replay</Head>
        <div className="space-y-4 p-4">
          <p className="text-[12.5px] text-fg-muted">
            Replaying the original (failing) trace should <span className="text-fail">FAIL</span>; a fixed run should{" "}
            <span className="text-ok">PASS</span>. Send a fixed run with{" "}
            <code className="rounded bg-ink-900 px-1.5 py-0.5 font-mono text-[11.5px] text-fg-muted">FIXED=1 make send-trace</code>{" "}
            then paste its trace_id.
          </p>
          <ReplayControls caseId={c.id} sourceTraceId={c.source_trace_id} />
        </div>
        {replays.length > 0 && (
          <div className="border-t border-line">
            {replays.map((r, i) => {
              const errs = Array.isArray((r.detail as { erroring_steps?: string[] })?.erroring_steps)
                ? (r.detail as { erroring_steps: string[] }).erroring_steps
                : [];
              return (
                <div
                  key={i}
                  className="grid grid-cols-[70px_1fr_auto] items-center gap-3 border-b border-line/50 px-4 py-2.5 text-[12px] last:border-0"
                >
                  <Badge variant={verdictVariant(r.verdict)}>{r.verdict}</Badge>
                  <span className="truncate font-mono text-[11.5px] text-fg-muted">
                    {r.candidate_trace_id.slice(0, 16)}…
                    {errs.length > 0 && <span className="ml-2 text-fail">errors: {errs.join(", ")}</span>}
                  </span>
                  <span className="font-mono text-[11px] text-fg-faint">{r.created_at?.slice(11, 19)}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function Head({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-b border-line px-4 py-3 text-[13px] font-semibold text-fg">{children}</div>
  );
}

function Meta({ k, v, href }: { k: string; v: string; href?: string }) {
  const inner = (
    <div className="px-4 py-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">{k}</div>
      <div className="mt-1 font-mono text-[13px] text-fg">{v}</div>
    </div>
  );
  return href ? (
    <a href={href} className="transition-colors hover:bg-white/[0.025]">
      {inner}
    </a>
  ) : (
    inner
  );
}

function Assertion({ k, v, ok }: { k: string; v: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-fg-faint">{k}</span>
      <span className={ok === undefined ? "text-fg" : ok ? "text-ok" : "text-fail"}>{v}</span>
    </div>
  );
}
