import { NextRequest, NextResponse } from "next/server";

// Client-side lazy-load proxy: one trace's spans + scores (used when an assistant message is
// expanded to reveal its steps). Mirrors lib/api.ts::getTrace but reachable from the browser.
const API = process.env.TRACELY_API ?? "http://localhost:8000";
const KEY = process.env.TRACELY_KEY ?? "tracely_dev_key";

export async function GET(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id") ?? "";
  if (!id) return NextResponse.json({ trace_id: "", spans: [], scores: [], eval_verdict: null });
  const r = await fetch(`${API}/api/traces/${encodeURIComponent(id)}`, {
    headers: { Authorization: `Bearer ${KEY}` },
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
