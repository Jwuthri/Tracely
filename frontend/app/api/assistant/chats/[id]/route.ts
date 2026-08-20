import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// One conversation: GET reopens it from history, DELETE removes it.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

async function proxy(method: "GET" | "DELETE", id: string) {
  const r = await fetch(`${API}/api/assistant/chats/${encodeURIComponent(id)}`, {
    method,
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  return proxy("GET", (await params).id);
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  return proxy("DELETE", (await params).id);
}
