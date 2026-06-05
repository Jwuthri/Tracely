import { NextRequest, NextResponse } from "next/server";

const API = process.env.TRACELY_API ?? "http://localhost:8000";
const KEY = process.env.TRACELY_KEY ?? "tracely_dev_key";

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q") ?? "";
  const r = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`, {
    headers: { Authorization: `Bearer ${KEY}` },
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
