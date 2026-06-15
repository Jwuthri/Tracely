import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: an evaluator's labeling queue (recent judge decisions + this reviewer's label).
// Maps to backend /api/calibration/{name}/queue.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const limit = req.nextUrl.searchParams.get("limit") || "100";
  const r = await fetch(
    `${API}/api/calibration/${encodeURIComponent(name)}/queue?limit=${encodeURIComponent(limit)}`,
    { headers: await authHeaders(), cache: "no-store" },
  );
  return NextResponse.json(await r.json(), { status: r.status });
}
