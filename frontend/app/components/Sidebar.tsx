"use client";

import clsx from "clsx";
import { usePathname } from "next/navigation";
import { IconActivity, IconGate, IconGrid, IconShield } from "./icons";

const NAV = [
  {
    group: "Observe",
    items: [
      { href: "/", label: "Dashboard", Icon: IconGrid, exact: true },
      { href: "/traces", label: "Traces", Icon: IconActivity },
    ],
  },
  {
    group: "Test",
    items: [{ href: "/cases", label: "Regression cases", Icon: IconShield }],
  },
  {
    group: "Ship",
    items: [{ href: "/gates", label: "CI gates", Icon: IconGate }],
  },
];

function Mark() {
  return (
    <div className="relative grid h-9 w-9 place-items-center rounded-[11px] border border-signal/30 bg-signal/10 shadow-[0_0_22px_-6px_rgba(34,211,238,0.7)]">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
        <path d="M12 2 22 12 12 22 2 12Z" stroke="#22d3ee" strokeWidth="1.8" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="2.7" fill="#22d3ee" />
      </svg>
    </div>
  );
}

export function Sidebar() {
  const path = usePathname();
  return (
    <aside className="sticky top-0 hidden h-screen w-[244px] shrink-0 flex-col border-r border-line bg-ink-900/80 backdrop-blur-md md:flex">
      <div className="flex items-center gap-3 px-5 pb-6 pt-6">
        <Mark />
        <div className="leading-none">
          <div className="font-display text-[19px] font-extrabold tracking-tight text-fg">Tracely</div>
          <div className="mt-1.5 font-mono text-[9.5px] uppercase tracking-[0.22em] text-fg-faint">
            trace-native ci/cd
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-7 px-3 py-1">
        {NAV.map((sec) => (
          <div key={sec.group}>
            <div className="px-3 pb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-fg-faint">
              {sec.group}
            </div>
            <div className="space-y-0.5">
              {sec.items.map(({ href, label, Icon, exact }) => {
                const active = exact ? path === href : path === href || path.startsWith(href + "/");
                return (
                  <a
                    key={href}
                    href={href}
                    className={clsx(
                      "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] transition-colors",
                      active ? "bg-signal/10 text-fg" : "text-fg-muted hover:bg-white/[0.03] hover:text-fg",
                    )}
                  >
                    {active && (
                      <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-signal shadow-[0_0_8px_rgba(34,211,238,0.7)]" />
                    )}
                    <Icon
                      className={clsx(
                        "h-[17px] w-[17px] transition-colors",
                        active ? "text-signal" : "text-fg-faint group-hover:text-fg-muted",
                      )}
                    />
                    {label}
                  </a>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-4 py-4">
        <div className="flex items-center justify-between rounded-lg border border-line bg-ink-800 px-3 py-2">
          <div className="leading-tight">
            <div className="text-[12.5px] text-fg">default</div>
            <div className="font-mono text-[9.5px] uppercase tracking-wider text-fg-faint">project</div>
          </div>
          <span className="flex items-center gap-1.5 rounded-md bg-ok/10 px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-wide text-ok">
            <span className="h-1.5 w-1.5 animate-pulse2 rounded-full bg-ok" />
            prod
          </span>
        </div>
        <div className="mt-3 px-1 font-mono text-[10px] text-fg-faint">v0.1.0 · MVP</div>
      </div>
    </aside>
  );
}
