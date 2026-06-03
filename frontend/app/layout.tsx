import "./globals.css";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";

export const metadata = {
  title: "Tracely — trace-native CI/CD for AI agents",
  description: "Production traces become regression tests.",
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
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="bg-grid relative flex min-h-screen flex-1 flex-col">
            <Topbar />
            <main className="mx-auto w-full max-w-[1240px] flex-1 px-8 py-8">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
