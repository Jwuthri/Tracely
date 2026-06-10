import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy: "Use AI" — natural-language description → draft evaluator config.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const r = await fetch(`${API}/api/evaluators/generate`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
