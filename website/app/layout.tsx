import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Tracely — trace-native CI/CD for AI agents",
  description:
    "Production traces become regression tests. Tracely grades every agent run, clusters failures into issues, freezes them as hermetic cases, and blocks the PR that reintroduces them.",
};

const FONTS =
  "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&family=Hanken+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href={FONTS} rel="stylesheet" />
      </head>
      <body className="min-h-screen bg-ink-950 font-sans text-fg antialiased">{children}</body>
    </html>
  );
}
