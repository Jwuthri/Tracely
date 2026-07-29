import { getStats } from "@/app/lib/api";
import { WipeDataPanel } from "@/app/components/WipeDataPanel";

export default async function DataSettingsPage() {
  const stats = await getStats();

  return (
    <div className="space-y-7">
      <header className="reveal">
        <h1 className="font-display text-[24px] font-extrabold tracking-tight">Data</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          What this project currently holds, and how to clear it out.
        </p>
      </header>

      <section className="reveal card grid grid-cols-2 divide-x divide-line/60 sm:grid-cols-4">
        <Stat k="Traces" v={stats.traces} />
        <Stat k="Spans" v={stats.spans} />
        <Stat k="Agents" v={stats.agents} />
        <Stat k="Regression cases" v={stats.cases} />
      </section>

      <WipeDataPanel />
    </div>
  );
}

function Stat({ k, v }: { k: string; v: number }) {
  return (
    <div className="px-4 py-3.5">
      <div className="font-mono text-[10.5px] uppercase tracking-wider text-fg-faint">{k}</div>
      <div className="mt-1 font-display text-[20px] font-bold tabular-nums">
        {v.toLocaleString()}
      </div>
    </div>
  );
}
