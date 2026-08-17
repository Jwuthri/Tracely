import { NextResponse } from "next/server";

import { authHeaders } from "@/app/lib/auth";
import { setActiveProject } from "@/app/lib/auth/cookie";

const API = process.env.TRACELY_API ?? "http://localhost:8000";

/** Remove a seat: your own (leave) or a teammate's (owners/admins). When you leave, the backend
 *  hands back a workspace you can still reach — point the active-workspace cookie at it, or the
 *  next request 403s on the one you just walked out of. */
export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ userId: string }> },
) {
  const { userId } = await params;
  const r = await fetch(`${API}/auth/members/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await r.json().catch(() => ({}));
  if (r.ok && data?.switch_to) await setActiveProject(data.switch_to);
  return NextResponse.json(data, { status: r.status });
}
