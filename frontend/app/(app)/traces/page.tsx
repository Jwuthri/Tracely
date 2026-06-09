import { getSessions } from "@/app/lib/api";
import { TracesExplorer } from "@/app/components/TracesExplorer";

// First page is rendered server-side for fast first paint; TracesExplorer pages/filters from there.
const PAGE = 50;

export default async function TracesPage() {
  const threads = await getSessions({ limit: PAGE });
  return (
    <div className="space-y-6">
      <header className="reveal">
        <h1 className="font-display text-[26px] font-extrabold tracking-tight">Traces</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          Agent runs grouped into conversation threads — expand any conversation into its messages and steps.
        </p>
      </header>

      <TracesExplorer initial={threads} pageSize={PAGE} hasMore={threads.length === PAGE} />
    </div>
  );
}
