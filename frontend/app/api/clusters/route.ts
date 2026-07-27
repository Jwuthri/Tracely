import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side proxy for cluster multi-select delete: { cluster_ids: [...] }.
// (Per-cluster promote/ignore go through /api/cluster.)
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function DELETE(req: NextRequest) {
  const r = await fetch(`${API}/api/clusters`, {
    method: "DELETE",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
