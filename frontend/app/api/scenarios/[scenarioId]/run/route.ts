import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

// Drive one scenario against its agent's endpoint. Returns the conversation id straight away —
// the driving is a background task, so this is a link to watch, not a result to wait for.
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ scenarioId: string }> },
) {
  const { scenarioId } = await params;
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/api/scenarios/${scenarioId}/run`, {
    method: "POST",
    headers: { ...(await authHeaders()), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
