import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

// Mint-only proxy. Reading a shared conversation does NOT come through here — that path is
// anonymous and server-rendered by /share/[token].
export async function POST(req: NextRequest) {
  const { threadId } = await req.json();
  const r = await fetch(`${API}/api/share`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId }),
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
