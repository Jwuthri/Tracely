import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const agent = req.nextUrl.searchParams.get("agent");
  const r = await fetch(`${API}/api/scenarios${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${API}/api/scenarios`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
