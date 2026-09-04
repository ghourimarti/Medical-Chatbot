import type { ReactNode } from "react";

/**
 * Clerk, but OPTIONAL (S21 / D24) — and configured at RUNTIME, not baked into the image.
 *
 * Accounts are a deployment choice. With no publishable key the provider is not rendered at
 * all, no Clerk JavaScript is loaded, and the app behaves exactly as it did before S21 —
 * anonymous chat, anonymous conversations, no sign-in affordance anywhere.
 *
 * This mirrors the backend, which uses a DisabledVerifier when CLERK_JWKS_URL is empty. A
 * frontend that showed a sign-in button against a backend that cannot verify tokens would
 * be offering a door with no room behind it.
 *
 * WHY THE KEY IS PASSED AS A PROP RATHER THAN READ BY THE CLIENT.
 * `NEXT_PUBLIC_*` is INLINED INTO THE CLIENT BUNDLE AT BUILD TIME. Relying on that would
 * mean the Docker image carries one specific Clerk instance, and the Dockerfile's stated
 * invariant — "ONE image runs in every environment, configured at runtime" — would quietly
 * stop being true. Worse, it fails silently: with the key absent at build the bundle bakes
 * an empty string, and no amount of setting it in `env_file` afterwards has any effect,
 * because there is nothing left to configure.
 *
 * This file is a SERVER component, so `process.env` here is read when the container starts,
 * not when the image was built. Passing `publishableKey` explicitly keeps the image
 * portable and makes `docker compose up` with a new key actually work.
 *
 * The import is dynamic so an unconfigured deployment never pays for the SDK.
 */
export function accountsEnabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);
}

export async function AuthShell({ children }: { children: ReactNode }) {
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  if (!publishableKey) return <>{children}</>;
  const { ClerkProvider } = await import("@clerk/nextjs");
  return <ClerkProvider publishableKey={publishableKey}>{children}</ClerkProvider>;
}
