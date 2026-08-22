import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** Natural language → a rule draft. A model call, so never cached. */
export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${API}/api/monitors/generate`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
