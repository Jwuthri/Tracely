import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// One attachment on its way to object storage. The multipart body is piped through untouched —
// re-encoding it here would mean buffering the whole file just to rebuild the same boundary.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const r = await fetch(`${API}/api/assistant/upload`, {
    method: "POST",
    headers: {
      ...(await authHeaders()),
      "content-type": req.headers.get("content-type") ?? "multipart/form-data",
    },
    body: req.body,
    cache: "no-store",
    // @ts-expect-error — duplex is required by undici for streaming request bodies
    duplex: "half",
  });
  return NextResponse.json(await r.json().catch(() => ({ detail: "upload failed" })), {
    status: r.status,
  });
}
