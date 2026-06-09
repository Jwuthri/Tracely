import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const { agent, env } = await req.json();
  const r = await fetch(`${API}/api/gate`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify({ agent: agent ?? "planner", env: env ?? "ci" }),
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
