import { CommandPalette } from "@/app/components/CommandPalette";
import { MissingLlmKeyBanner } from "@/app/components/MissingLlmKeyBanner";
import { QuotaBanner } from "@/app/components/QuotaBanner";
import { Sidebar } from "@/app/components/Sidebar";
import { Topbar } from "@/app/components/Topbar";
import { getBillingUsage, getLlmKeyConfigured } from "@/app/lib/api";
import { getMe, requireSession } from "@/app/lib/auth";

// Authed dashboard shell. requireSession() is defense-in-depth behind middleware; in dev mode it
// always resolves (synthetic ingest session) so the app stays open with no login wall.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  // One parallel round: identity + the two shell banners' probes (LLM key, quota). Serial awaits
  // here would add a per-navigation round trip for every banner.
  const [me, llmConfigured, usage] = await Promise.all([
    getMe(),
    getLlmKeyConfigured(),
    getBillingUsage(),
  ]);
  return (
    <div className="flex min-h-screen">
      <Sidebar me={me} />
      <div className="bg-grid relative flex min-h-screen flex-1 flex-col">
        <Topbar />
        <MissingLlmKeyBanner configured={llmConfigured} />
        <QuotaBanner usage={usage} />
        <main className="mx-auto w-full max-w-[1240px] flex-1 px-8 py-8">{children}</main>
      </div>
      <CommandPalette />
    </div>
  );
}
