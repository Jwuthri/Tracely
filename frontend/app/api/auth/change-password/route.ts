import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";
import { setSessionCookie } from "@/app/lib/auth/cookie";

// Browser proxy: change the signed-in local user's password.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/auth/change-password`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  // A password change ends every session, THIS one included — swap in the fresh token the backend
  // hands back or the user logs themselves out by changing their password.
  if (r.ok && data.token) {
    await setSessionCookie(data.token);
    return NextResponse.json({ ok: true }, { status: 200 });
  }
  return NextResponse.json(data, { status: r.status });
}
