import { NextRequest } from "next/server";
import { authHeaders } from "@/app/lib/auth";

// Serve an attachment back to the transcript (image thumbnails, download links). The backend
// decides what may render inline; this hop only forwards its answer, headers included.
const API = process.env.TRACELY_API ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await fetch(`${API}/api/assistant/files/${encodeURIComponent(id)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  if (!r.ok || !r.body) return new Response("not found", { status: r.status });
  return new Response(r.body, {
    status: 200,
    headers: {
      "content-type": r.headers.get("content-type") ?? "application/octet-stream",
      "content-disposition": r.headers.get("content-disposition") ?? "attachment",
      "x-content-type-options": "nosniff",
      "cache-control": "private, max-age=3600",
    },
  });
}
