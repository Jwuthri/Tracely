import { NextResponse } from "next/server";

const API = process.env.TRACELY_API ?? "http://localhost:8000";
const KEY = process.env.TRACELY_KEY ?? "tracely_dev_key";

export async function POST() {
  const r = await fetch(`${API}/api/clusters/rebuild`, {
    method: "POST",
    headers: { Authorization: `Bearer ${KEY}` },
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
