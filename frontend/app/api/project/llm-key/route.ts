import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side proxy for the Settings -> LLM key panel. TRACELY_KEY/TRACELY_API never reach the
// browser — every request re-issues here with the Bearer key attached server-side.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/api/project/llm-key`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}

export async function PUT(req: NextRequest) {
  const r = await fetch(`${API}/api/project/llm-key`, {
    method: "PUT",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(await req.json().catch(() => ({}))),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}

export async function DELETE() {
  const r = await fetch(`${API}/api/project/llm-key`, {
    method: "DELETE",
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
