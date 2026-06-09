import { NextResponse } from "next/server";
import { clearActiveProject, clearSessionCookie } from "@/app/lib/auth/cookie";

export async function POST() {
  await clearSessionCookie();
  await clearActiveProject();
  return NextResponse.json({ ok: true });
}
