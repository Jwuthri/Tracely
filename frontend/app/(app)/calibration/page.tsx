import { CalibrationView } from "@/app/components/CalibrationView";

export const metadata = { title: "Judge calibration · Tracely" };

export default function CalibrationPage() {
  return (
    <div className="space-y-6">
      <header className="reveal">
        <h1 className="font-display text-[26px] font-extrabold tracking-tight">Judge calibration</h1>
        <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
          Before you let an LLM judge block your CI, check it against yourself. Grade a random sample
          of runs — you first, the judge revealed after — and Tracely tracks how often it matches you
          and which way it errs: missed failures, or good PRs it would have blocked.
        </p>
      </header>
      <CalibrationView />
    </div>
  );
}
