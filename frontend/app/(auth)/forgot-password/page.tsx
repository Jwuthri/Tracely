"use client";

import { useState } from "react";
import { AuthShell, Field, FormError, Submit } from "../_ui";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    const r = await fetch("/api/auth/forgot-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email }),
    });
    // Success is shown whether or not the address has an account — the backend refuses to say,
    // and the UI must not leak the difference either.
    if (r.ok) setSent(true);
    else setErr("Something went wrong. Try again.");
    setLoading(false);
  }

  if (sent) {
    return (
      <AuthShell
        title="Check your email"
        subtitle="If that address has an account, a reset link is on its way."
        footer={
          <a href="/login" className="text-signal hover:underline">
            Back to sign in
          </a>
        }
      >
        <p className="text-[13px] leading-relaxed text-fg-muted">
          The link expires in 1 hour and can be used once. Nothing has changed on your account
          until you open it.
        </p>
        <p className="mt-3 text-[12.5px] leading-relaxed text-fg-faint">
          Self-hosting without email configured? Run{" "}
          <code className="text-fg-muted">python -m tracely.auth.reset_link {email || "<email>"}</code>{" "}
          on the backend to print the link.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="We'll email you a link to set a new one."
      footer={
        <a href="/login" className="text-signal hover:underline">
          Back to sign in
        </a>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <FormError>{err}</FormError>
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoFocus
          autoComplete="email"
          placeholder="you@company.com"
        />
        <Submit loading={loading}>Send reset link</Submit>
      </form>
    </AuthShell>
  );
}
