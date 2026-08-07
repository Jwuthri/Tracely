import { getStats } from "@/app/lib/api";
import { DeleteWorkspacePanel } from "@/app/components/DeleteWorkspacePanel";
import { SeedDataPanel } from "@/app/components/SeedDataPanel";
import { WipeDataPanel } from "@/app/components/WipeDataPanel";
import { getMe } from "@/app/lib/auth";

export default async function DataSettingsPage() {
  const [stats, me] = await Promise.all([getStats(), getMe()]);
  // Deleting the workspace is an owner/admin action; the backend enforces it too, this just
  // keeps the button out of a member's way.
  const canDelete = me?.role === "OWNER" || me?.role === "ADMIN";
  const siblings = (me?.projects ?? []).filter(
    (p) => p.organization_id === me?.organization_id && p.id !== me?.project_id,
  );

  return (
    <div className="space-y-7">
      <header className="reveal">
        <h1 className="font-display text-[24px] font-extrabold tracking-tight">Data</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          What this project currently holds, how to fill it, and how to clear it out.
        </p>
      </header>

      <section className="reveal card grid grid-cols-2 divide-x divide-line/60 sm:grid-cols-4">
        <Stat k="Traces" v={stats.traces} />
        <Stat k="Spans" v={stats.spans} />
        <Stat k="Agents" v={stats.agents} />
        <Stat k="Regression cases" v={stats.cases} />
      </section>

      <SeedDataPanel empty={stats.traces === 0} />

      <WipeDataPanel />

      {canDelete && (
        <DeleteWorkspacePanel
          name={me?.project_name ?? "this workspace"}
          onlyWorkspace={siblings.length === 0}
        />
      )}
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
