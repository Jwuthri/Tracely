import { NextRequest, NextResponse } from "next/server";

import { authHeaders } from "@/app/lib/auth";
import { setActiveProject } from "@/app/lib/auth/cookie";

// Delete the ACTIVE workspace. The backend takes no id — it deletes whatever `X-Tracely-Project`
// resolves to — so this proxy can't be aimed at another tenant either. On success the cookie is
// pointed at the surviving sibling the backend names, or every subsequent request would 403 on a
// workspace that no longer exists and bounce the user to /login.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function DELETE(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/api/project`, {
    method: "DELETE",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify({ confirm: String(body?.confirm ?? "") }),
    cache: "no-store",
  });
  const data = await r.json().catch(() => ({}));
  if (r.ok && data?.switch_to) await setActiveProject(data.switch_to);
  return NextResponse.json(data, { status: r.status });
}
