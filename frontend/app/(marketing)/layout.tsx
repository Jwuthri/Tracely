// Bare, full-bleed layout for the public marketing page — no sidebar/topbar shell, no auth.
// data-theme="dark" pins the landing to the palette it was art-directed in: the app has a light
// theme, but the marketing page's gradients, glass and glows are a dark composition, and the
// tokens are inherited, so pinning the wrapper repaints the whole subtree correctly.
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div data-theme="dark" className="min-h-screen bg-ink-950 text-fg">
      {children}
    </div>
  );
}
