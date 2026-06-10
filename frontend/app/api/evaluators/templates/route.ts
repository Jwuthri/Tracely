import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy: the evaluator template library (Browse Library in Add Column).
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/api/evaluators/templates`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
