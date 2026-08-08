import { DeleteOrganizationPanel } from "@/app/components/DeleteOrganizationPanel";
import { InviteManager } from "@/app/components/InviteManager";
import { MembersList } from "@/app/components/MembersList";
import { getAuthMode, getMe } from "@/app/lib/auth";

export default async function TeamPage() {
  const me = await getMe();
  const mode = getAuthMode();
  const allowed = me?.role === "OWNER" || me?.role === "ADMIN";
  const personal = me?.organization_kind === "personal";

  return (
    <div className="space-y-7">
      <header className="reveal">
        <h1 className="font-display text-[24px] font-extrabold tracking-tight">Team</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          {personal
            ? "This is your personal account — it holds one workspace and can't be shared."
            : `Everyone in ${me?.organization_name || "this organization"} can reach all of its workspaces.`}
        </p>
      </header>

      {personal ? (
        <div className="card p-6 text-[13px] leading-relaxed text-fg-muted">
          To work with other people, create an organization from the account menu. Organizations
          hold several workspaces and let you invite teammates; your personal account stays
          yours alone.
        </div>
      ) : (
        <>
          <MembersList />
          {mode !== "local" ? (
            // Clerk owns invitations in hosted mode — the local invite endpoints aren't mounted.
            <div className="card p-6 text-[13px] text-fg-muted">
              Invitations are managed in your identity provider.
            </div>
          ) : allowed ? (
            <InviteManager />
          ) : (
            <div className="card p-6 text-[13px] text-fg-muted">
              Only owners and admins can invite teammates.
            </div>
          )}
          <DeleteOrganizationPanel
            name={me?.organization_name ?? "this organization"}
            canDelete={me?.role === "OWNER"}
          />
        </>
      )}
    </div>
  );
}
