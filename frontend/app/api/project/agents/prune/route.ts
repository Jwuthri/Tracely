import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side proxy for Settings → Data → "Clean up agents".
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST() {
  const r = await fetch(`${API}/api/project/agents/prune`, {
    method: "POST",
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
