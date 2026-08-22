import { notFound } from "next/navigation";
import { RuleEditor } from "@/app/components/alerts/RuleEditor";
import { DocLink } from "@/app/components/DocLink";
import { fromMonitor } from "@/app/lib/alerts";
import { getAgents, getEvaluators, getMonitor } from "@/app/lib/api";
import type { FlowLayout, StepDraft } from "@/app/lib/ruleFlow";

export const metadata = { title: "Alert · Tracely" };

export default async function EditAlertPage({ params }: { params: Promise<{ monitorId: string }> }) {
  const { monitorId } = await params;
  const monitor = await getMonitor(monitorId);
  if (monitor === null) notFound();

  const [agents, evaluators] = await Promise.all([getAgents(), getEvaluators()]);
  const scoreNames = [
    ...new Set(
      evaluators
        .slice()
        .sort((a, b) => Number(b.enabled) - Number(a.enabled))
        .map((e) => e.score_name)
        .filter((n): n is string => Boolean(n)),
    ),
  ];

  return (
    <div className="space-y-6">
      <header className="reveal">
        <div className="flex items-center gap-3">
          <a href="/settings/alerts" className="text-[12.5px] text-fg-faint transition-colors hover:text-fg">
            ← Alerts
          </a>
          <DocLink path="/product/alerts" />
        </div>
        <h1 className="mt-1.5 font-display text-[24px] font-extrabold tracking-tight">{monitor.name}</h1>
      </header>

      <RuleEditor
        monitorId={monitor.id}
        initialDraft={fromMonitor(monitor)}
        initialSteps={(monitor.steps ?? []) as StepDraft[]}
        initialLayout={(monitor.flow_layout ?? null) as FlowLayout | null}
        agents={agents}
        scoreNames={scoreNames}
      />
    </div>
  );
}
