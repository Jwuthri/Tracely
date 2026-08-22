import { DocLink } from "@/app/components/DocLink";
import { BillingActions } from "@/app/components/BillingActions";
import { Meter } from "@/app/components/Meter";
import { Badge } from "@/app/components/ui";
import { getBillingUsage } from "@/app/lib/api";
import { getMe } from "@/app/lib/auth";

export const metadata = { title: "Usage & billing · Tracely" };

const PLAN_LABEL: Record<string, string> = {
  free: "Free",
  pro: "Pro",
  unlimited: "Unlimited",
};

/** Meter color follows the same threshold story as the shell banner: calm → warn at 80% → fail
 *  once ingest is being rejected. */
function meterTone(frac: number): string {
  if (frac >= 1) return "bg-fail/70";
  if (frac >= 0.8) return "bg-warn/70";
  return "bg-signal/60";
}

export default async function BillingPage() {
  const [usage, me] = await Promise.all([getBillingUsage(), getMe()]);
  // Owners and admins can start/manage a subscription; members, dev mode (role null) and
  // ingest principals see the numbers read-only.
  const canManage = me?.role === "OWNER" || me?.role === "ADMIN";

  return (
    <div className="space-y-6">
      <header className="reveal">
        <div className="flex items-center gap-3"><h1 className="font-display text-[24px] font-extrabold tracking-tight">Usage &amp; billing</h1><DocLink path="/product/settings#usage--billing" /></div>
        <p className="mt-1.5 max-w-2xl text-[14px] text-fg-muted">
          Traces ingested this month, your plan, and — on the hosted cloud — the subscription
          behind it. Billing belongs to{" "}
          {me?.organization_name ? (
            <span className="text-fg">{me.organization_name}</span>
          ) : (
            "your account"
          )}
          , not to a single workspace.
        </p>
      </header>

      {!usage ? (
        <div className="reveal card px-4 py-10 text-center text-[13px] text-fg-faint">
          Could not load usage — the backend is unreachable.
        </div>
      ) : !usage.billing_enabled ? (
        <section className="reveal card overflow-hidden">
          <div className="border-b border-line px-4 py-3 text-[13px] font-semibold text-fg">Self-hosted</div>
          <p className="px-4 py-4 text-[13.5px] leading-relaxed text-fg-muted">
            This deployment has no trace limits and no billing — every feature is yours already.
            The hosted cloud at{" "}
            <a href="https://tracely-ai.com" className="text-signal hover:underline">
              tracely-ai.com
            </a>{" "}
            runs the same code with a free plan and managed infrastructure.
          </p>
        </section>
      ) : (
        <BillingUsageCard
          usage={usage}
          canManage={canManage}
          personal={me?.organization_kind === "personal"}
        />
      )}
    </div>
  );
}

function BillingUsageCard({
  usage,
  canManage,
  personal,
}: {
  usage: NonNullable<Awaited<ReturnType<typeof getBillingUsage>>>;
  canManage: boolean;
  personal: boolean;
}) {
  const capped = usage.trace_limit != null && usage.trace_limit > 0;
  const frac = capped ? usage.traces_used / (usage.trace_limit as number) : 0;
  return (
    <section className="reveal card overflow-hidden" style={{ animationDelay: "60ms" }}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold text-fg">Current plan</span>
          <Badge variant={usage.plan === "free" ? "neutral" : "signal"} dot>
            {PLAN_LABEL[usage.plan] ?? usage.plan}
          </Badge>
        </div>
        <span className="font-mono text-[10.5px] uppercase tracking-wider text-fg-faint">
          period {usage.period} (UTC)
        </span>
      </div>

      <div className="space-y-3 px-4 py-4">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-display text-[22px] font-bold tabular-nums text-fg">
            {usage.traces_used.toLocaleString()}
            <span className="ml-1.5 text-[13px] font-normal text-fg-muted">
              {capped ? `of ${(usage.trace_limit as number).toLocaleString()} traces` : "traces · no limit"}
            </span>
          </span>
          {capped && (
            <span className="font-mono text-[11.5px] tabular-nums text-fg-muted">
              {Math.min(999, Math.round(frac * 100))}%
            </span>
          )}
        </div>

        {capped && <Meter value={frac * 100} segments={20} tone={meterTone(frac)} />}

        {frac >= 1 && (
          <p className="rounded-lg border border-fail/30 bg-fail/10 px-3 py-2 text-[13px] text-fail">
            The quota is reached — new traces are rejected (HTTP 429) until the month rolls over
            {usage.plan === "free" ? " or you upgrade." : "."}
          </p>
        )}

        <p className="text-[12.5px] leading-relaxed text-fg-faint">
          A trace counts once per month, on ingest. Tracely&apos;s own recordings (evaluations,
          scenario drives) never count against your quota.
          {usage.quota_scope === "account" &&
            (personal
              ? " Your personal account holds one workspace; create an organization to run several on one plan."
              : " Every workspace in this organization shares the quota and the subscription — adding workspaces doesn't add quota.")}
        </p>

        <BillingActions plan={usage.plan} canManage={canManage} />
      </div>
    </section>
  );
}
