import { CommandPalette } from "@/app/components/CommandPalette";
import { Sidebar } from "@/app/components/Sidebar";
import { Topbar } from "@/app/components/Topbar";
import { getMe, requireSession } from "@/app/lib/auth";

// Authed dashboard shell. requireSession() is defense-in-depth behind middleware; in dev mode it
// always resolves (synthetic ingest session) so the app stays open with no login wall.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  const me = await getMe();
  return (
    <div className="flex min-h-screen">
      <Sidebar me={me} />
      <div className="bg-grid relative flex min-h-screen flex-1 flex-col">
        <Topbar />
        <main className="mx-auto w-full max-w-[1240px] flex-1 px-8 py-8">{children}</main>
      </div>
      <CommandPalette />
    </div>
  );
}
