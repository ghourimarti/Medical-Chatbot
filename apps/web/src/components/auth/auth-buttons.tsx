"use client";

import { useEffect, useRef } from "react";
import { SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";

/**
 * Sign-in affordance and the post-sign-in claim (S21).
 *
 * Rendered only when accounts are configured — see AuthShell. Kept in its own client
 * component so the Clerk hooks never appear in a build without a publishable key.
 *
 * BRANCHES ON `useAuth()`, NOT ON <SignedIn>/<SignedOut>. Those control components are
 * still EXPORTED by @clerk/nextjs 7 but throw at render under Clerk Core 3
 * ("<SignedOut> is not available in @clerk/nextjs Core 3"), which is a particularly
 * unhelpful failure: the import resolves, typecheck passes, the build succeeds, and the
 * component explodes in the browser at runtime. `useAuth` is the primitive both of them
 * are built on and has been stable across these versions, so branching on it directly
 * removes a whole class of upgrade breakage.
 *
 * `isLoaded` is checked before rendering anything: Clerk resolves the session
 * asynchronously, and rendering "Log in" first would flash a sign-in prompt at somebody
 * who is already signed in, on every single page load.
 */
export function AuthButtons({ onSignedIn }: { onSignedIn: () => void }) {
  const { isSignedIn, isLoaded } = useAuth();
  const claimed = useRef(false);

  useEffect(() => {
    // Claim ONCE per page life, on the transition into signed-in. The endpoint is
    // idempotent (a second call claims zero), but calling it on every render would be a
    // request storm for no benefit.
    if (!isLoaded || !isSignedIn || claimed.current) return;
    claimed.current = true;
    onSignedIn();
  }, [isLoaded, isSignedIn, onSignedIn]);

  // Nothing until Clerk knows. Reserving no space is deliberate — a placeholder sized for
  // two buttons would shift the whole header when the real state arrives.
  if (!isLoaded) return null;

  if (isSignedIn) {
    // afterSignOutUrl was removed in Clerk 7; the default post-sign-out route is fine.
    return <UserButton />;
  }

  return (
    <>
      {/* Log in AND sign up, both in the header, because that is where someone looks for
          them. Sign-up is the filled control: creating an account is what makes threads
          follow you to another device, and `claim` above is what stops the ones you
          already have being stranded when you do. */}
      <SignInButton mode="modal">
        <button className="rounded-full px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken">
          Log in
        </button>
      </SignInButton>
      <SignUpButton mode="modal">
        <button className="rounded-full bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast hover:opacity-90">
          Sign up
        </button>
      </SignUpButton>
    </>
  );
}
