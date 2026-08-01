import { NextRequest, NextResponse } from "next/server";
import { setSessionCookie } from "@/app/lib/auth/cookie";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

// A successful reset returns a session, same as accept-invite — the user is already proving
// control of the account, so making them log in again immediately adds nothing.
export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${API}/auth/reset-password`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return NextResponse.json(data, { status: r.status });
  await setSessionCookie(data.token);
  return NextResponse.json({ ok: true });
}
