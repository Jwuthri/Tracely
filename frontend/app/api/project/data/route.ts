import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side proxy for the Settings → Data danger zone. Body: { confirm: "DELETE" } — forwarded
// verbatim so the backend stays the one place that enforces the guard.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function DELETE(req: NextRequest) {
  const r = await fetch(`${API}/api/project/data`, {
    method: "DELETE",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(await req.json().catch(() => ({}))),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
