import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy: per-evaluator LLM-judge token usage (the cost of each judge column).
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: Request) {
  const days = new URL(req.url).searchParams.get("days") ?? "30";
  const r = await fetch(`${API}/api/evaluators/cost?days=${encodeURIComponent(days)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
