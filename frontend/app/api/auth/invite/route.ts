import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// OWNER/ADMIN only (enforced by the backend via the forwarded session). GET lists, POST creates.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/auth/invitations`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${API}/auth/invitations`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

// Revoke a pending invite (soft: backend flips PENDING -> REVOKED, invalidating the token).
export async function DELETE(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id");
  if (!id) return NextResponse.json({ detail: "missing invite id" }, { status: 400 });
  const r = await fetch(`${API}/auth/invitations/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
