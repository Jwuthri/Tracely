import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// The caller's conversations, newest first — what the assistant's history panel lists.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET() {
  const r = await fetch(`${API}/api/assistant/chats`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => []), { status: r.status });
}
