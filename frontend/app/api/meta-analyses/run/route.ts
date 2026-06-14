import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: run a meta-analysis for an agent (or whole project). POST { agent_id }.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/api/meta-analyses/run`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ agent_id: body?.agent_id ?? "" }),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
