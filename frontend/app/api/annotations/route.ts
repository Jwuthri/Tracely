import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: upsert (POST) / clear (DELETE) a human label on a judge score.
// Maps to backend /api/annotations.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

async function forward(req: NextRequest, method: "POST" | "DELETE") {
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/api/annotations`, {
    method,
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

export const POST = (req: NextRequest) => forward(req, "POST");
export const DELETE = (req: NextRequest) => forward(req, "DELETE");
