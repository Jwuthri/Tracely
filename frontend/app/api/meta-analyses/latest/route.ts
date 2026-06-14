import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: latest stored analysis for an agent. GET ?agent_id= (blank/"all" → whole project).
// Maps to backend /api/meta-analyses/agent/{agent_id}; returns { analysis: <result|null> }.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const agent = req.nextUrl.searchParams.get("agent_id") || "all";
  const r = await fetch(`${API}/api/meta-analyses/agent/${encodeURIComponent(agent)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
