import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Browser-side proxy: curated judge-model choices for the Add Column form.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function GET() {
  const r = await fetch(`${API}/api/evaluators/models`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
