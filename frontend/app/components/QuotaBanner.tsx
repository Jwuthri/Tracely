import Link from "next/link";

import type { BillingUsage } from "@/app/lib/api";

/** Shell-wide quota warning (hosted cloud only). Quiet until 80% of the monthly trace cap,
 *  amber to 100%, red once ingest is being rejected. The layout fetches usage (in parallel with
 *  the LLM-key probe) and passes it in; null / billing-disabled / uncapped render nothing. */
export function QuotaBanner({ usage }: { usage: BillingUsage | null }) {
  if (!usage?.billing_enabled || !usage.trace_limit) return null;
  const frac = usage.traces_used / usage.trace_limit;
  if (frac < 0.8) return null;
  const over = frac >= 1;
  const tone = over ? "border-fail/30 bg-fail/10 text-fail" : "border-warn/30 bg-warn/10 text-warn";
  return (
    <div className="mx-auto w-full max-w-[1240px] px-8 pt-6">
      <div
        className={`flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border px-4 py-3 text-[13px] ${tone}`}
      >
        <span className="font-semibold">
          {over ? "Monthly trace quota reached" : "Approaching your trace quota"}
        </span>
        <span className="text-fg-muted">
          {usage.traces_used.toLocaleString()} of {usage.trace_limit.toLocaleString()} traces this
          month{usage.quota_scope === "account" ? " across your workspaces" : ""}
          {over ? " — new traces are being rejected until the month rolls over." : "."}
        </span>
        <Link
          href="/settings/billing"
          className={`font-medium underline underline-offset-2 ${over ? "text-fail" : "text-warn"}`}
        >
          {usage.plan === "free" ? "Upgrade" : "View usage"}
        </Link>
      </div>
    </div>
  );
}
