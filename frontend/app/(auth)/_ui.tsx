"use client";

import type { ReactNode } from "react";

function Mark() {
  return (
    <div className="relative grid h-11 w-11 place-items-center rounded-[13px] border border-signal/30 bg-signal/10 shadow-[0_0_28px_-6px_rgba(34,211,238,0.7)]">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <path d="M12 2 22 12 12 22 2 12Z" stroke="#22d3ee" strokeWidth="1.8" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="2.7" fill="#22d3ee" />
      </svg>
    </div>
  );
}

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="w-full max-w-[400px]">
      <div className="mb-8 flex flex-col items-center text-center">
        <Mark />
        <h1 className="mt-4 font-display text-[24px] font-extrabold tracking-tight text-fg">{title}</h1>
        {subtitle && <p className="mt-1.5 text-[13.5px] text-fg-muted">{subtitle}</p>}
      </div>
      <div className="card p-7">{children}</div>
      {footer && <div className="mt-5 text-center text-[12.5px] text-fg-faint">{footer}</div>}
    </div>
  );
}

export function Field({
  label,
  type = "text",
  value,
  onChange,
  placeholder,
  autoFocus,
  autoComplete,
  minLength,
}: {
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  autoComplete?: string;
  minLength?: number;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.18em] text-fg-faint">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        autoComplete={autoComplete}
        minLength={minLength}
        required
        className="w-full rounded-lg border border-line bg-ink-800 px-3.5 py-2.5 text-[14px] text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-signal/50"
      />
    </label>
  );
}

export function Submit({ loading, children }: { loading?: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="w-full rounded-lg bg-signal px-4 py-2.5 text-[14px] font-semibold text-ink transition-opacity hover:opacity-90 disabled:opacity-60"
    >
      {loading ? "…" : children}
    </button>
  );
}

export function FormError({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <div className="rounded-lg border border-fail/30 bg-fail/10 px-3.5 py-2.5 text-[12.5px] text-fail">
      {children}
    </div>
  );
}
