import type { ReactNode } from "react";

/**
 * Clerk, but OPTIONAL (S21 / D24).
 *
 * Accounts are a deployment choice. With no publishable key the provider is not rendered at
 * all, no Clerk JavaScript is loaded, and the app behaves exactly as it did before S21 —
 * anonymous chat, anonymous conversations, no sign-in affordance anywhere.
 *
 * This mirrors the backend, which uses a DisabledVerifier when CLERK_JWKS_URL is empty. A
 * frontend that showed a sign-in button against a backend that cannot verify tokens would
 * be offering a door with no room behind it.
 *
 * The import is dynamic so an unconfigured deployment never pays for the SDK.
 */
export const accountsEnabled = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

export async function AuthShell({ children }: { children: ReactNode }) {
  if (!accountsEnabled) return <>{children}</>;
  const { ClerkProvider } = await import("@clerk/nextjs");
  return <ClerkProvider>{children}</ClerkProvider>;
}
