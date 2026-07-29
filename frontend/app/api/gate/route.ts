import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const { agent, env } = await req.json();
  const r = await fetch(`${API}/api/gate`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    // no agent fallback — an unset agent is a 400 from the backend, not a guess at a slug
    body: JSON.stringify({ agent, env: env ?? "ci" }),
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
