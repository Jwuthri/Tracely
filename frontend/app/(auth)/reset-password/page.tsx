"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthShell, Field, FormError, Submit } from "../_ui";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token") || "");
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setErr("Those passwords don't match.");
      return;
    }
    setLoading(true);
    setErr(null);
    const r = await fetch("/api/auth/reset-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, new_password: password }),
    });
    if (r.ok) {
      router.push("/dashboard");
      router.refresh();
    } else {
      const d = await r.json().catch(() => ({}));
      setErr(d.detail || "This reset link is invalid or has expired.");
      setLoading(false);
    }
  }

  return (
    <AuthShell
      title="Set a new password"
      subtitle="Then you'll be signed straight in."
      footer={
        <a href="/forgot-password" className="text-signal hover:underline">
          Request a new link
        </a>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <FormError>
          {!token ? "Missing reset token — open the link from your email." : err}
        </FormError>
        <Field
          label="New password"
          type="password"
          value={password}
          onChange={setPassword}
          autoFocus
          autoComplete="new-password"
          minLength={8}
          placeholder="At least 8 characters"
        />
        <Field
          label="Confirm password"
          type="password"
          value={confirm}
          onChange={setConfirm}
          autoComplete="new-password"
          minLength={8}
          placeholder="Type it again"
        />
        <Submit loading={loading}>Set password &amp; sign in</Submit>
      </form>
    </AuthShell>
  );
}
