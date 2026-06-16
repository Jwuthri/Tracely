import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy: one monitor (patch / delete). Mirrors backend /api/monitors/{id}.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await fetch(`${API}/api/monitors/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: await req.text(),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function DELETE(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await fetch(`${API}/api/monitors/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
