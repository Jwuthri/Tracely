// Session-cookie helpers for local mode (set on login/register/accept, cleared on logout).
import "server-only";

import { cookies } from "next/headers";

import { ACTIVE_PROJECT_COOKIE, SESSION_COOKIE } from "./index";

const MAX_AGE = Number(process.env.SESSION_TTL_SECONDS ?? 604800); // 7 days

export async function setSessionCookie(token: string): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax", // survives the post-login top-level redirect and the accept-invite link
    secure: process.env.NODE_ENV === "production", // MUST be false on http://localhost or the cookie is dropped
    path: "/",
    maxAge: MAX_AGE,
  });
}

export async function clearSessionCookie(): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
}

// ── active-workspace selection (read by authHeaders) ────────────────────────────

export async function setActiveProject(projectId: string): Promise<void> {
  (await cookies()).set(ACTIVE_PROJECT_COOKIE, projectId, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE,
  });
}

export async function getActiveProject(): Promise<string | null> {
  return (await cookies()).get(ACTIVE_PROJECT_COOKIE)?.value ?? null;
}

export async function clearActiveProject(): Promise<void> {
  (await cookies()).set(ACTIVE_PROJECT_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
}
