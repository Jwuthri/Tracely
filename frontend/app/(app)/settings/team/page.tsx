import { InviteManager } from "@/app/components/InviteManager";
import { getMe } from "@/app/lib/auth";

export default async function TeamPage() {
  const me = await getMe();
  const allowed = me?.role === "OWNER" || me?.role === "ADMIN";

  return (
    <div className="space-y-7">
      <header className="reveal">
        <h1 className="font-display text-[24px] font-extrabold tracking-tight">Team</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          Invite teammates to {me?.project_name || "this workspace"}.
        </p>
      </header>
      {allowed ? (
        <InviteManager />
      ) : (
        <div className="card p-6 text-[13px] text-fg-muted">
          Only workspace owners and admins can manage teammates.
        </div>
      )}
    </div>
  );
}
