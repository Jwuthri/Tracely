import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** "Does this actually reach me?" — runs the rule's flow against a chosen subject (or evaluates a
 *  threshold rule's live window). Real side effects, on purpose. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ monitorId: string }> }) {
  const { monitorId } = await params;
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/api/monitors/${monitorId}/test`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
