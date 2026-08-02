import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** Queue the demo seeder for this workspace — the Data page's "Seed demo data" button. */
export async function POST() {
  const r = await fetch(`${API}/api/project/seed`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
