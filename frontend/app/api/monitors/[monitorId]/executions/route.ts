import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest, { params }: { params: Promise<{ monitorId: string }> }) {
  const { monitorId } = await params;
  const limit = req.nextUrl.searchParams.get("limit") ?? "20";
  const r = await fetch(`${API}/api/monitors/${monitorId}/executions?limit=${encodeURIComponent(limit)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
