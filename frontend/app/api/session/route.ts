import { NextRequest, NextResponse } from "next/server";

// Client-side lazy-load proxy: a conversation thread's turns (used when a row is expanded
// in the hierarchical trace table). Mirrors lib/api.ts::getSession but reachable from the browser.
const API = process.env.TRACELY_API ?? "http://localhost:8000";
const KEY = process.env.TRACELY_KEY ?? "tracely_dev_key";

export async function GET(req: NextRequest) {
  const thread = req.nextUrl.searchParams.get("thread") ?? "";
  if (!thread) return NextResponse.json({ thread_id: "", turns: [] });
  const r = await fetch(`${API}/api/sessions/${encodeURIComponent(thread)}`, {
    headers: { Authorization: `Bearer ${KEY}` },
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
