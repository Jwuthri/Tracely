// Bare, centered layout for unauthenticated pages (login / register / accept-invite / Clerk sign-in).

// Login screens in Google's index are pure noise: they rank for the brand name, outrank the page
// that actually sells the product, and leak the invite/reset routes.
export const metadata = { title: "Sign in", robots: { index: false, follow: false } };

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className="grid min-h-screen place-items-center bg-ink px-4 py-10">{children}</div>;
}
