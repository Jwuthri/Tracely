"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthShell, Field, FormError, Submit } from "../_ui";

export default function RegisterPage() {
  const router = useRouter();
  const [workspace, setWorkspace] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    const r = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password, workspace_name: workspace || "Tracely" }),
    });
    if (r.ok) {
      router.push("/");
      router.refresh();
    } else {
      const d = await r.json().catch(() => ({}));
      setErr(
        r.status === 409
          ? "This workspace is already set up — ask an owner for an invite."
          : d.detail || "Registration failed",
      );
      setLoading(false);
    }
  }

  return (
    <AuthShell
      title="Create your workspace"
      subtitle="You'll be the owner of this Tracely instance."
      footer={
        <>
          Already have an account?{" "}
          <a href="/login" className="text-signal hover:underline">
            Sign in
          </a>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <FormError>{err}</FormError>
        <Field label="Workspace name" value={workspace} onChange={setWorkspace} autoFocus placeholder="Acme AI" />
        <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" placeholder="you@company.com" />
        <Field label="Password" type="password" value={password} onChange={setPassword} autoComplete="new-password" minLength={8} placeholder="At least 8 characters" />
        <Submit loading={loading}>Create workspace</Submit>
      </form>
    </AuthShell>
  );
}
