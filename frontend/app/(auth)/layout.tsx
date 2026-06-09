// Bare, centered layout for unauthenticated pages (login / register / accept-invite / Clerk sign-in).
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className="grid min-h-screen place-items-center bg-ink px-4 py-10">{children}</div>;
}
