// Server-only auth surface. One module the rest of the app codes against, with three runtime modes
// selected by NEXT_PUBLIC_AUTH_MODE. The Clerk path is dynamically imported so local/dev builds never
// initialize Clerk (which throws without keys).
import "server-only";

import { cookies } from "next/headers";

import type { AuthMode, Me, Session } from "./types";

export const SESSION_COOKIE = "tracely_session";
// The user's currently-selected workspace (project). Forwarded as X-Tracely-Project so every
// server-side data fetch (and /auth/me) is scoped to it; the backend enforces membership.
export const ACTIVE_PROJECT_COOKIE = "tracely_project";
const API = process.env.TRACELY_API ?? "http://localhost:8000";
const DEV_KEY = process.env.TRACELY_KEY ?? "tracely_dev_key";

export function getAuthMode(): AuthMode {
  const m = process.env.NEXT_PUBLIC_AUTH_MODE;
  return m === "local" || m === "clerk" ? m : "dev";
}

export async function getSession(): Promise<Session | null> {
  const mode = getAuthMode();
  if (mode === "clerk") {
    const { auth } = await import("@clerk/nextjs/server");
    const a = await auth();
    if (!a.userId) return null;
    const token = await a.getToken();
    return token ? { token } : null;
  }
  if (mode === "local") {
    const token = (await cookies()).get(SESSION_COOKIE)?.value;
    return token ? { token } : null;
  }
  // dev: no human auth — forward the ingest key (today's behavior, non-breaking)
  return { token: DEV_KEY };
}

/** The header replacement for the old static `{ Authorization: Bearer KEY }`. Empty when unauthed.
 * Adds X-Tracely-Project when the user has picked a workspace, so reads target the right tenant. */
export async function authHeaders(): Promise<Record<string, string>> {
  const s = await getSession();
  if (!s) return {};
  const headers: Record<string, string> = { Authorization: `Bearer ${s.token}` };
  const project = (await cookies()).get(ACTIVE_PROJECT_COOKIE)?.value;
  if (project) headers["X-Tracely-Project"] = project;
  return headers;
}

/** For authed server pages: defense-in-depth behind middleware. Redirects when unauthed. */
export async function requireSession(): Promise<Session> {
  const s = await getSession();
  if (!s) {
    const { redirect } = await import("next/navigation");
    redirect(getAuthMode() === "clerk" ? "/sign-in" : "/login");
  }
  return s as Session;
}

/** Fetch the full identity (workspace, role, ingest keys) from the backend. */
export async function getMe(): Promise<Me | null> {
  const headers = await authHeaders();
  if (!headers.Authorization) return null;
  try {
    const r = await fetch(`${API}/auth/me`, { headers, cache: "no-store" });
    return r.ok ? ((await r.json()) as Me) : null;
  } catch {
    return null;
  }
}

export type { AuthMode, Me, Session } from "./types";
