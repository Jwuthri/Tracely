import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** Turn a real conversation into a scenario — the flow behind "Save as scenario" on a session. */
export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${API}/api/scenarios/import`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
