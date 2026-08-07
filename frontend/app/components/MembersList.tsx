"use client";

import { useEffect, useState } from "react";

import type { Member } from "@/app/lib/auth/types";

/** Who is in the organization. Everyone here can reach every workspace in the account, which is
 *  exactly why it's worth showing — an invite is not scoped to one workspace. */
export function MembersList() {
  const [members, setMembers] = useState<Member[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch("/api/auth/members")
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setMembers(Array.isArray(d) ? d : []))
      .catch(() => setMembers([]))
      .finally(() => setLoaded(true));
  }, []);

  if (!loaded) return null;

  return (
    <section className="card overflow-hidden">
      <div className="flex items-baseline justify-between gap-3 border-b border-line px-5 py-3">
        <span className="text-[13px] font-semibold text-fg">Members</span>
        <span className="font-mono text-[10.5px] uppercase tracking-wider text-fg-faint">
          {members.length} {members.length === 1 ? "seat" : "seats"} used
        </span>
      </div>
      <ul>
        {members.map((m) => (
          <li
            key={m.user_id}
            className="flex items-center justify-between gap-3 border-b border-line/50 px-5 py-2.5 last:border-b-0"
          >
            <span className="min-w-0">
              <span className="block truncate text-[13px] text-fg">
                {m.display_name || m.email}
              </span>
              {m.display_name && (
                <span className="block truncate text-[11.5px] text-fg-faint">{m.email}</span>
              )}
            </span>
            <span className="shrink-0 font-mono text-[10.5px] uppercase tracking-wider text-fg-muted">
              {m.role}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
