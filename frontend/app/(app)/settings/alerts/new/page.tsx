import { notFound } from "next/navigation";
import { RuleEditor } from "@/app/components/alerts/RuleEditor";
import { DocLink } from "@/app/components/DocLink";
import { RECIPES, TRIGGERS, emptyDraft } from "@/app/lib/alerts";
import { newStepId, type StepDraft } from "@/app/lib/ruleFlow";
import { getAgents, getEvaluators } from "@/app/lib/api";

export const metadata = { title: "New alert · Tracely" };

/** A new rule, optionally seeded from a recipe (`?recipe=<index>`). The recipe's steps get ids
 *  here, which is what makes a recipe data rather than a half-saved rule. */
export default async function NewAlertPage({
  searchParams,
}: {
  searchParams: Promise<{ recipe?: string }>;
}) {
  const { recipe } = await searchParams;
  const index = recipe === undefined ? -1 : Number(recipe);
  if (recipe !== undefined && (Number.isNaN(index) || index < 0 || index >= RECIPES.length)) notFound();
  const picked = index >= 0 ? RECIPES[index] : undefined;

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

  const draft = emptyDraft(picked?.draft ?? {});
  const steps: StepDraft[] = (picked?.steps ?? []).map((s, i) => ({
    id: newStepId(),
    order_index: i,
    name: s.name,
    step_type: s.step_type,
    config: s.config,
  }));

  return (
    <div className="space-y-6">
      <header className="reveal">
        <div className="flex items-center gap-3">
          <h1 className="font-display text-[24px] font-extrabold tracking-tight">
            {picked ? picked.title : "New alert"}
          </h1>
          <DocLink path="/product/alerts" />
        </div>
        <p className="mt-1.5 max-w-3xl text-[13.5px] text-fg-muted">
          {picked ? picked.why : `Pick what fires it, then draw what happens. Trigger: ${TRIGGERS[draft.type].label}.`}
        </p>
      </header>

      <RuleEditor
        monitorId={null}
        initialDraft={draft}
        initialSteps={steps}
        initialLayout={null}
        agents={agents}
        scoreNames={scoreNames}
      />
    </div>
  );
}
