import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Client-side proxy for deleting one regression case (the case detail page's Delete button).
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function DELETE(_req: Request, { params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params;
  const r = await fetch(`${API}/api/cases/${encodeURIComponent(caseId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
