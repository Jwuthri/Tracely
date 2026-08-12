import type { Metadata } from "next";

import "./globals.css";
import { AuthRootProvider } from "./_providers/AuthRootProvider";
import { SITE_DESCRIPTION, SITE_TITLE, SITE_URL } from "./lib/site";

// Site-wide defaults. `metadataBase` is what turns the relative OG/canonical paths every other
// route emits into the absolute URLs Google and Slack require — without it Next warns and falls
// back to localhost. Individual routes override `title`/`description`; the (app), (auth) and
// /share routes additionally override `robots` to noindex.
// ponytail: no `keywords` meta — Google has ignored it since 2009, and Bing treats it as spam.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: SITE_TITLE, template: "%s — Tracely" },
  description: SITE_DESCRIPTION,
  applicationName: "Tracely",
  openGraph: {
    type: "website",
    siteName: "Tracely",
    url: SITE_URL,
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
  },
  twitter: { card: "summary_large_image", title: SITE_TITLE, description: SITE_DESCRIPTION },
  robots: { index: true, follow: true },
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
      <body className="min-h-screen bg-ink font-sans text-fg antialiased">
        {/* The dashboard shell (sidebar/topbar) lives in the (app) route group; (auth) pages render bare. */}
        <AuthRootProvider>{children}</AuthRootProvider>
      </body>
    </html>
  );
}
