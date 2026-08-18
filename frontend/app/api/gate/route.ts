import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const { agent, env, case_ids } = await req.json();
  const r = await fetch(`${API}/api/gate`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    // no agent fallback — an unset agent is a 400 from the backend, not a guess at a slug
    // `case_ids` only when the launcher picked a subset: absent means the whole suite, and
    // forwarding an undefined would drop the key anyway — being explicit is the point.
    body: JSON.stringify({ agent, env: env ?? "ci", ...(case_ids ? { case_ids } : {}) }),
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
