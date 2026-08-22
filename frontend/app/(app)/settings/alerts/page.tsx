import { AlertsList } from "@/app/components/alerts/AlertsList";
import { DocLink } from "@/app/components/DocLink";
import { getMonitors } from "@/app/lib/api";

export const metadata = { title: "Alerts · Tracely" };

export default async function AlertsPage() {
  const monitors = await getMonitors();
  return (
    <div className="space-y-6">
      <header className="reveal">
        <div className="flex items-center gap-3">
          <h1 className="font-display text-[26px] font-extrabold tracking-tight">Alerts</h1>
          <DocLink path="/product/alerts" />
        </div>
        <p className="mt-1.5 max-w-3xl text-[14px] text-fg-muted">
          Workspace rules with two halves: <span className="text-fg">when</span> — a CI gate fails, a live
          conversation breaks on a judge, a failure mode appears that nobody has seen before, or a rate crosses a line
          — and <span className="text-fg">what happens</span>, drawn as a flow: conditions, Slack, email, a webhook
          with your own headers, an LLM step whose answer the next step can use.
        </p>
      </header>

      <AlertsList initial={monitors} />
    </div>
  );
}
