import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ monitorId: string }> },
) {
  const { monitorId } = await params;
  const body = await req.json();
  const r = await fetch(`${API}/api/monitors/${monitorId}`, {
    method: "PATCH",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ monitorId: string }> },
) {
  const { monitorId } = await params;
  const r = await fetch(`${API}/api/monitors/${monitorId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
