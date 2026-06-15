import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: per-evaluator judge-vs-human agreement summary. Mirrors backend /api/calibration.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/api/calibration`, { headers: await authHeaders(), cache: "no-store" });
  return NextResponse.json(await r.json(), { status: r.status });
}
