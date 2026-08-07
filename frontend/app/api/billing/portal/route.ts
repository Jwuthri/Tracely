import { NextResponse } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// BFF proxy for the Stripe billing-portal redirect (card, cancel, invoices).
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export async function POST() {
  const r = await fetch(`${API}/api/billing/portal`, {
    method: "POST",
    headers: await authHeaders(),
    cache: "no-store",
  });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
