"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthShell, Field, FormError, Submit } from "../_ui";

export default function AcceptInvitePage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token") || "");
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    const r = await fetch("/api/auth/accept-invite", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, password, display_name: name }),
    });
    if (r.ok) {
      router.push("/");
      router.refresh();
    } else {
      const d = await r.json().catch(() => ({}));
      setErr(d.detail || "Could not accept invitation");
      setLoading(false);
    }
  }

  return (
    <AuthShell title="Accept your invitation" subtitle="Set a password to join the workspace.">
      <form onSubmit={onSubmit} className="space-y-4">
        <FormError>
          {!token ? "Missing invitation token — open the link from your invite." : err}
        </FormError>
        <Field label="Your name" value={name} onChange={setName} autoFocus placeholder="Jane Doe" />
        <Field label="Password" type="password" value={password} onChange={setPassword} autoComplete="new-password" minLength={8} placeholder="At least 8 characters" />
        <Submit loading={loading}>Join workspace</Submit>
      </form>
    </AuthShell>
  );
}
