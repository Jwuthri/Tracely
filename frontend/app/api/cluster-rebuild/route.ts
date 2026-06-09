import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST() {
  const r = await fetch(`${API}/api/clusters/rebuild`, {
    method: "POST",
    headers: await authHeaders(),
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
