import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: monitors collection (list + create). Mirrors backend /api/monitors.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/api/monitors`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function POST(req: Request) {
  const r = await fetch(`${API}/api/monitors`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: await req.text(),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
