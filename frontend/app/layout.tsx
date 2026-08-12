import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";

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

// next/font downloads these at BUILD time and serves them from our own origin, which removes the
// render-blocking round-trip to fonts.googleapis.com. That single request was costing 956ms of
// blocked render on mobile (Lighthouse, 2026-08-12) for a 2KB stylesheet — the cost was the DNS +
// TLS + request to a third-party origin, not the payload. It also self-hosts the .woff2 files, so
// the second hop to fonts.gstatic.com goes away too, along with both preconnects.
// The `variable` names must match the CSS custom properties tailwind.config.ts reads.
const fontSans = Hanken_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-sans",
  display: "swap",
});
const fontDisplay = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-display",
  display: "swap",
});
const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
  display: "swap",
});

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${fontSans.variable} ${fontDisplay.variable} ${fontMono.variable}`}
    >
      <body className="min-h-screen bg-ink font-sans text-fg antialiased">
        {/* The dashboard shell (sidebar/topbar) lives in the (app) route group; (auth) pages render bare. */}
        <AuthRootProvider>{children}</AuthRootProvider>
      </body>
    </html>
  );
}
