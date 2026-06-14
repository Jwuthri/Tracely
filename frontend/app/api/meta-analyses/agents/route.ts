import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy for the meta-analysis agent selector. Mirrors backend /api/meta-analyses/agents.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/api/meta-analyses/agents`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
