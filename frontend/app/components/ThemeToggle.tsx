"use client";

import { useEffect, useState } from "react";

/* Two themes, one switch. The chosen theme lives in localStorage and is applied to <html> by
   the inline script in app/layout.tsx BEFORE first paint — this component only flips it and
   shows which one is on, so it never causes the flash it exists to avoid. */

export type Theme = "dark" | "light";
export const THEME_KEY = "tracely-theme";

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // private mode / storage disabled: the theme still applies for this page
  }
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  // Render the dark icon until mounted: the server has no idea which theme this browser stored,
  // and guessing produces a hydration mismatch on every light-theme page load.
  const [theme, setTheme] = useState<Theme | null>(null);
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  }, []);

  const next: Theme = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
      title={`Switch to ${next} theme`}
      aria-label={`Switch to ${next} theme`}
      className={`grid h-8 w-8 place-items-center rounded-lg border border-line bg-ink-800 text-fg-faint transition-colors hover:border-signal/40 hover:text-fg ${className}`}
    >
      {theme === "light" ? <IconMoon className="h-4 w-4" /> : <IconSun className="h-4 w-4" />}
    </button>
  );
}

function IconSun(p: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" {...p}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
    </svg>
  );
}

function IconMoon(p: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...p}>
      <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.6 6.6 0 0 0 10.5 10.5Z" />
    </svg>
  );
}
