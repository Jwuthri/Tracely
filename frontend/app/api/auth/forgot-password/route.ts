import { NextRequest, NextResponse } from "next/server";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

// Pass-through: the backend deliberately answers the same for known and unknown emails, so this
// route must not add any branching that would let the browser tell them apart.
export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${API}/auth/forgot-password`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  return NextResponse.json(data, { status: r.status });
}
