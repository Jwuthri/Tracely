import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** Start a gate that drives the agent's scenarios against its endpoint. Returns immediately with
 *  a RUNNING gate id — real HTTP calls plus grading take minutes, so the caller polls
 *  `/api/gates/{id}` until `finished_at` is set. */
export async function POST(req: NextRequest) {
  const { agent, env, min_pass_rate } = await req.json();
  const r = await fetch(`${API}/api/gate/simulate`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify({ agent, env: env ?? "ci", min_pass_rate }),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
