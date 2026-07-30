import { LlmKeyPanel } from "@/app/components/LlmKeyPanel";

export default function LlmSettingsPage() {
  return (
    <div className="space-y-7">
      <header className="reveal">
        <h1 className="font-display text-[24px] font-extrabold tracking-tight">LLM key</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          The OpenRouter key evaluation LLM calls use for this workspace.
        </p>
      </header>

      <LlmKeyPanel />
    </div>
  );
}
