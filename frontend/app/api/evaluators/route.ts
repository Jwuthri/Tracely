import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy: list + create evaluators (the trace table's evaluation columns).
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/api/evaluators`, { headers: await authHeaders(), cache: "no-store" });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function POST(req: NextRequest) {
  const r = await fetch(`${API}/api/evaluators`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
