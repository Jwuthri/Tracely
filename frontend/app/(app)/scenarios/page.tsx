import { DocLink } from "@/app/components/DocLink";
import { getAgents, getScenarios } from "@/app/lib/api";
import { ScenariosManager } from "@/app/components/ScenariosManager";

export default async function ScenariosPage() {
  const [agents, scenarios] = await Promise.all([getAgents(), getScenarios()]);
  // Surface agents that already have scenarios first. A project can have dozens of registered
  // agents, and defaulting to whichever came back first lands you on an empty one every time
  // (same reason /gates ranks by promoted-case count).
  const counts: Record<string, number> = {};
  for (const s of scenarios) counts[s.agent_id] = (counts[s.agent_id] ?? 0) + 1;
  const ranked = [...agents].sort((a, b) => (counts[b.id] ?? 0) - (counts[a.id] ?? 0));

  return (
    <div className="space-y-6">
      <header className="reveal">
        <div className="flex items-center gap-3"><h1 className="font-display text-[26px] font-extrabold tracking-tight">Scenarios</h1><DocLink path="/product/scenarios" /></div>
        <p className="mt-1.5 max-w-3xl text-[14px] text-fg-muted">
          Multi-turn conversations Tracely drives against your agent&apos;s own endpoint. Each run
          lands as a real trace — graded by your evaluators, aggregated into the{" "}
          <span className="text-fg">CI gate</span>. Author one here, or import a conversation that
          actually broke in production from its session page.
        </p>
      </header>

      {agents.length === 0 ? (
        <div className="reveal card px-4 py-14 text-center text-[13px] text-fg-faint">
          No agents yet — send a trace first, then register the endpoint to drive.
        </div>
      ) : (
        <ScenariosManager agents={ranked} counts={counts} initial={scenarios} />
      )}
    </div>
  );
}
