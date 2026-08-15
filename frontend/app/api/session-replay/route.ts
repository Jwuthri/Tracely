import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side proxy for one conversation's replay script.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const thread = req.nextUrl.searchParams.get("thread") ?? "";
  if (!thread) return NextResponse.json({ actors: [], events: [], duration_ms: 0 });
  const r = await fetch(`${API}/api/sessions/${encodeURIComponent(thread)}/replay`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
