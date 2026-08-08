import { NextRequest, NextResponse } from "next/server";

import { authHeaders, getMe } from "@/app/lib/auth";
import { setActiveProject } from "@/app/lib/auth/cookie";

// Create a company organization (the backend also mints its first workspace), then switch into
// that workspace so the user lands inside the account they just made. The backend answers 409
// with the reason when a cap is hit; pass status + body through so the menu can show it.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** Delete the caller's organization and every workspace in it. The backend returns a workspace
 *  that still exists; point the active-workspace cookie at it, or the next request 403s on a
 *  dead id and the app bounces the user to /login. */
export async function DELETE(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/auth/organizations`, {
    method: "DELETE",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify({ confirm: String(body?.confirm ?? "") }),
    cache: "no-store",
  });
  const data = await r.json().catch(() => ({}));
  if (r.ok && data?.switch_to) await setActiveProject(data.switch_to);
  return NextResponse.json(data, { status: r.status });
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const name = String(body?.name ?? "").trim();
  if (!name) return NextResponse.json({ error: "name required" }, { status: 400 });
  const r = await fetch(`${API}/auth/organizations`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify({ name }),
    cache: "no-store",
  });
  const data = await r.json().catch(() => ({}));
  if (r.ok && data?.id) {
    const me = await getMe();
    const fresh = me?.projects.find((p) => p.organization_id === data.id);
    if (fresh) await setActiveProject(fresh.id);
  }
  return NextResponse.json(data, { status: r.status });
}
