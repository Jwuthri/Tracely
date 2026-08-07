import { NextResponse } from "next/server";

import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** The caller's organization members. Any member may list their teammates. */
export async function GET() {
  const res = await fetch(`${API}/auth/members`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json().catch(() => []);
  return NextResponse.json(data, { status: res.status });
}
