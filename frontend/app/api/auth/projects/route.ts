import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";
import { setActiveProject } from "@/app/lib/auth/cookie";

// Create a new workspace (backend mints its Project + OWNER membership + ingest key) and immediately
// switch to it, so the user lands in the fresh workspace and /settings/api-keys shows its key.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const name = String(body?.name ?? "").trim();
  if (!name) return NextResponse.json({ error: "name required" }, { status: 400 });
  const r = await fetch(`${API}/auth/projects`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify({ name }),
    cache: "no-store",
  });
  const data = await r.json().catch(() => ({}));
  if (r.ok && data?.id) await setActiveProject(data.id);
  return NextResponse.json(data, { status: r.status });
}
