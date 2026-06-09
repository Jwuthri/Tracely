// Wraps the app in <ClerkProvider> only when AUTH_MODE=clerk. The dynamic import keeps Clerk entirely
// out of the local/dev module graph — ClerkProvider throws without keys, and self-host builds shouldn't
// need Clerk env at all.
export async function AuthRootProvider({ children }: { children: React.ReactNode }) {
  if (process.env.NEXT_PUBLIC_AUTH_MODE === "clerk") {
    const { ClerkProvider } = await import("@clerk/nextjs");
    return <ClerkProvider>{children}</ClerkProvider>;
  }
  return <>{children}</>;
}
