import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: evaluate the monitor NOW (read live samples + dispatch alerts iff fires +
// dedup elapsed). Mirrors backend POST /api/monitors/{id}/test.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await fetch(`${API}/api/monitors/${encodeURIComponent(id)}/test`, {
    method: "POST",
    headers: await authHeaders(),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
