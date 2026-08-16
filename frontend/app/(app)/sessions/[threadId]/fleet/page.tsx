import { OfficeStage } from "@/app/components/replay/OfficeStage";

export const metadata = { title: "Fleet · Tracely" };

export default async function FleetPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = await params;
  return (
    <div className="space-y-6">
      <header className="reveal">
        <h1 className="font-display text-[26px] font-extrabold tracking-tight">Conv fleet</h1>
        <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
          The conversation as an office. Watch the agents work: handoffs walk across the floor,
          knowledge is read at the library, tools run at the wall — every beat is a real span.
        </p>
      </header>
      <OfficeStage threadId={decodeURIComponent(threadId)} />
    </div>
  );
}
