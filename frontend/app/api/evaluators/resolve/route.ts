import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy: resolve an advanced @VARIABLE prompt against a real trace/thread for the
// Add-Column modal's live preview (no LLM — just template substitution).
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const r = await fetch(`${API}/api/evaluators/resolve`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
