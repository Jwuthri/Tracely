import { CalibrationView } from "@/app/components/CalibrationView";

export const metadata = { title: "Judge calibration · Tracely" };

export default function CalibrationPage() {
  return (
    <div className="space-y-6">
      <header className="reveal">
        <h1 className="font-display text-[26px] font-extrabold tracking-tight">Judge calibration</h1>
        <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
          Before you let an LLM judge block your CI, check it against yourself. Agree or disagree with each
          verdict — Tracely tracks how often the judge matches you, and which way it errs.
        </p>
      </header>
      <CalibrationView />
    </div>
  );
}
