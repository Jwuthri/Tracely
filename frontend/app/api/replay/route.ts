import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const { caseId, candidateTraceId } = await req.json();
  const r = await fetch(`${API}/api/cases/${caseId}/replay`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(candidateTraceId ? { candidate_trace_id: candidateTraceId } : {}),
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
