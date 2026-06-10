import { NextRequest } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy for the SSE evaluation run: forwards the POST and pipes the
// `text/event-stream` body straight through so per-score frames reach the grid live.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const upstream = await fetch(`${API}/api/evaluations/run`, {
    method: "POST",
    headers: {
      ...(await authHeaders()),
      "content-type": "application/json",
      accept: "text/event-stream",
    },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
    // @ts-expect-error — duplex is required by undici for streaming request/response pairs
    duplex: "half",
  });
  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text();
    return new Response(text || JSON.stringify({ detail: "evaluation run failed" }), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
    },
  });
}
