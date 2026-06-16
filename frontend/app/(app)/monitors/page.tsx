import { MonitorsView } from "@/app/components/MonitorsView";

export const metadata = { title: "Monitors · Tracely" };

export default function MonitorsPage() {
  return (
    <div className="space-y-6">
      <header className="reveal">
        <h1 className="font-display text-[26px] font-extrabold tracking-tight">Monitors</h1>
        <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
          Threshold rules over the metrics you already collect — page Slack (or any webhook) when
          a quality judge starts failing, when a goal-success score drops, or when the trace
          failure rate spikes. Quiet by default; only fires when a condition crosses its
          threshold and the dedup interval has elapsed.
        </p>
      </header>
      <MonitorsView />
    </div>
  );
}
