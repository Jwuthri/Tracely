// Bare, full-bleed layout for the public marketing page — no sidebar/topbar shell, no auth.
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return <div className="bg-ink-950">{children}</div>;
}
