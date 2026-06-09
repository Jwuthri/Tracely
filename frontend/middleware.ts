import { NextResponse } from "next/server";
import type { NextFetchEvent, NextRequest } from "next/server";

// One guard, branching on the build-time auth mode. The Clerk path is dynamically imported inside the
// handler so local/dev runs never load Clerk (clerkMiddleware throws without keys). Node runtime — do
// NOT set runtime="edge" (the dynamic import relies on it).
const MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";
const SESSION_COOKIE = "tracely_session";

const PUBLIC = [
  /^\/login/,
  /^\/register/,
  /^\/accept-invite/,
  /^\/sign-in/,
  /^\/sign-up/,
  /^\/api\/health/,
  /^\/api\/auth\//,
];
const isPublic = (p: string) => PUBLIC.some((re) => re.test(p));

export default async function middleware(req: NextRequest, ev: NextFetchEvent) {
  if (MODE === "clerk") {
    const { clerkMiddleware, createRouteMatcher } = await import("@clerk/nextjs/server");
    const isPublicClerk = createRouteMatcher([
      "/sign-in(.*)",
      "/sign-up(.*)",
      "/api/health",
      "/api/auth/(.*)",
    ]);
    return clerkMiddleware(async (auth, r) => {
      if (!isPublicClerk(r)) await auth.protect();
    })(req, ev);
  }

  if (MODE === "local") {
    const { pathname } = req.nextUrl;
    if (isPublic(pathname)) return NextResponse.next();
    if (!req.cookies.get(SESSION_COOKIE)?.value) {
      // API calls get a clean 401 (the client fetches degrade gracefully); pages redirect to /login.
      if (pathname.startsWith("/api/")) {
        return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
      }
      const url = req.nextUrl.clone();
      url.pathname = "/login";
      url.searchParams.set("next", pathname);
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

  return NextResponse.next(); // dev: open, no auth wall
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff2?|ttf)).*)",
  ],
};
