import { SignUp } from "@clerk/nextjs";

// Clerk-mode only (see sign-in page note).
export const dynamic = "force-dynamic";

export default function SignUpPage() {
  if (process.env.NEXT_PUBLIC_AUTH_MODE !== "clerk") return null;
  return <SignUp />;
}
