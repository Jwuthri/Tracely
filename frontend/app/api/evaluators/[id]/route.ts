import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy: edit / delete one evaluator.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const r = await fetch(`${API}/api/evaluators/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const r = await fetch(`${API}/api/evaluators/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
