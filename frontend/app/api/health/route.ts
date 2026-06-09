import { NextResponse } from "next/server";

// Liveness probe + middleware allowlist anchor (always public in every auth mode).
export async function GET() {
  return NextResponse.json({ status: "ok" });
}
