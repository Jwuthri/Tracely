import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const qs = new URLSearchParams({
    trigger: sp.get("trigger") ?? "",
    subject_id: sp.get("subject_id") ?? "",
  });
  const r = await fetch(`${API}/api/monitors/inputs/sample?${qs}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
