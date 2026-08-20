import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser proxy for one chat turn. POST { message, chat_id?, attachments?, path } →
// { chat_id, title, reply } | { disabled: true }. Same idiom as every other app/api route:
// the Bearer key stays server-side.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await fetch(`${API}/api/assistant/chat`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({
      message: body?.message ?? "",
      chat_id: body?.chat_id ?? null,
      attachments: body?.attachments ?? [],
      path: body?.path ?? "",
    }),
  });
  return NextResponse.json(await r.json().catch(() => ({ detail: "the assistant is unreachable" })), {
    status: r.status,
  });
}
