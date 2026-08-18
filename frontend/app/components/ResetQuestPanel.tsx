"use client";

/** Restart the onboarding quest: drop its localStorage state and reload so the widget re-mounts
 *  fresh (un-dismissed, visits cleared, celebration re-armed). Data-derived steps re-tick from
 *  real counts on their own — that's the point, there is no stored progress to reset for them. */
export function ResetQuestPanel() {
  return (
    <section className="card p-5">
      <h2 className="text-[15px] font-semibold text-fg">Onboarding quest</h2>
      <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-fg-muted">
        Bring back the guided tour — the floating checklist that walks through keys, traces,
        evaluators, Trends, Replay, the Fleet and your first gate, plus the daily challenges.
        Restarting clears the page-visit progress, daily score and streak saved in this browser;
        steps backed by real data (traces sent, evaluators created, …) stay done.
      </p>
      <button
        type="button"
        className="btn-ghost mt-3"
        onClick={() => {
          localStorage.removeItem("tracely_quest_v1");
          location.reload();
        }}
      >
        Restart onboarding
      </button>
    </section>
  );
}
