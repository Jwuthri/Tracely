import { NextRequest, NextResponse } from "next/server";
import { getMe } from "@/app/lib/auth";
import { setActiveProject } from "@/app/lib/auth/cookie";

// Switch the active workspace: persist the choice in an httpOnly cookie that authHeaders() forwards as
// X-Tracely-Project. We validate the id against the user's memberships up front so a bad value can't
// 403 every subsequent data request.
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const projectId = String(body?.project_id ?? "");
  if (!projectId) return NextResponse.json({ error: "project_id required" }, { status: 400 });
  const me = await getMe();
  if (!me || !me.projects.some((p) => p.id === projectId)) {
    return NextResponse.json({ error: "not a member of that workspace" }, { status: 403 });
  }
  await setActiveProject(projectId);
  return NextResponse.json({ ok: true });
}
