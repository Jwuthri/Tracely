import { ChangePasswordForm } from "@/app/components/ChangePasswordForm";
import { getAuthMode, getMe } from "@/app/lib/auth";

export default async function AccountPage() {
  const me = await getMe();
  const mode = getAuthMode();

  return (
    <div className="space-y-7">
      <header className="reveal">
        <h1 className="font-display text-[24px] font-extrabold tracking-tight">Account</h1>
        <p className="mt-1.5 text-[14px] text-fg-muted">
          {me?.email ? `Signed in as ${me.email}.` : "Your account."}
        </p>
      </header>

      <section className="card p-5">
        <div className="mb-1 text-[13px] font-semibold text-fg">Password</div>
        <p className="mb-4 text-[12.5px] text-fg-faint">Update the password you sign in with.</p>
        {mode === "local" ? (
          <ChangePasswordForm />
        ) : (
          <p className="text-[13px] text-fg-faint">
            {mode === "clerk"
              ? "Your password is managed by your identity provider (Clerk)."
              : "No password in dev mode — access is via the ingest key."}
          </p>
        )}
      </section>
    </div>
  );
}
