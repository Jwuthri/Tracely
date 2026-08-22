import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const trigger = req.nextUrl.searchParams.get("trigger") ?? "";
  const r = await fetch(`${API}/api/monitors/inputs/schema?trigger=${encodeURIComponent(trigger)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
