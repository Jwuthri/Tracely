import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side lazy-load proxy: a conversation thread's turns (used when a row is expanded
// in the hierarchical trace table). Mirrors lib/api.ts::getSession but reachable from the browser.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const thread = req.nextUrl.searchParams.get("thread") ?? "";
  if (!thread) return NextResponse.json({ thread_id: "", turns: [] });
  const r = await fetch(`${API}/api/sessions/${encodeURIComponent(thread)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
