"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthShell, Field, FormError, Submit } from "../_ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (r.ok) {
      const next = new URLSearchParams(window.location.search).get("next") || "/";
      router.push(next);
      router.refresh();
    } else {
      const d = await r.json().catch(() => ({}));
      setErr(d.detail || "Invalid email or password");
      setLoading(false);
    }
  }

  return (
    <AuthShell
      title="Sign in to Tracely"
      subtitle="trace-native CI/CD for AI agents"
      footer="Need an account? Ask your workspace owner for an invite."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <FormError>{err}</FormError>
        <Field label="Email" type="email" value={email} onChange={setEmail} autoFocus autoComplete="email" placeholder="you@company.com" />
        <Field label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" placeholder="••••••••" />
        <Submit loading={loading}>Sign in</Submit>
      </form>
    </AuthShell>
  );
}
