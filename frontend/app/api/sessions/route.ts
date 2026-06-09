import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side proxy for the threads list — lets TracesExplorer page (offset) and re-query on a
// date-range change without a full server render. Mirrors lib/api.ts::getSessions but reachable from
// the browser. `from`/`to` are ISO-8601 (UTC); forwarded to the backend's from_ts/to_ts.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const qs = new URLSearchParams({
    limit: sp.get("limit") ?? "50",
    offset: sp.get("offset") ?? "0",
  });
  const from = sp.get("from");
  const to = sp.get("to");
  if (from) qs.set("from_ts", from);
  if (to) qs.set("to_ts", to);
  const r = await fetch(`${API}/api/sessions?${qs.toString()}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
