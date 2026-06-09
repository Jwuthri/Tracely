import { SignIn } from "@clerk/nextjs";

// Clerk-mode only. force-dynamic + the mode guard keep this out of local/dev prerendering (where
// Clerk has no provider/keys and would throw). Unreachable in local mode (middleware never routes here).
export const dynamic = "force-dynamic";

export default function SignInPage() {
  if (process.env.NEXT_PUBLIC_AUTH_MODE !== "clerk") return null;
  return <SignIn />;
}
