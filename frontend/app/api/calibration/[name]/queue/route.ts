import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: an evaluator's labeling queue (a sample of judge decisions + this reviewer's
// label). Maps to backend /api/calibration/{name}/queue. The query string is forwarded whole —
// it dropped everything but `limit`, so "Load more" re-fetched page 1 and appended it to itself.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const qs = req.nextUrl.search || "?limit=25";
  const r = await fetch(`${API}/api/calibration/${encodeURIComponent(name)}/queue${qs}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
