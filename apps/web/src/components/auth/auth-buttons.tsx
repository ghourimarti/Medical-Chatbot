"use client";

import { useEffect, useRef } from "react";
import { SignInButton, SignedIn, SignedOut, UserButton, useAuth } from "@clerk/nextjs";

/**
 * Sign-in affordance and the post-sign-in claim (S21).
 *
 * Rendered only when accounts are configured — see AuthShell. Kept in its own client
 * component so the Clerk hooks never appear in a build without a publishable key.
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

  return (
    <>
      <SignedOut>
        <SignInButton mode="modal">
          <button className="rounded-md px-2 py-1 text-xs text-ink-muted hover:bg-surface-sunken hover:text-ink">
            Sign in
          </button>
        </SignInButton>
      </SignedOut>
      <SignedIn>
        {/* afterSignOutUrl was removed in Clerk 7; the default post-sign-out route is fine. */}
        <UserButton />
      </SignedIn>
    </>
  );
}
