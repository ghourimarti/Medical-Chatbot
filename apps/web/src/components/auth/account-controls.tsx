"use client";

import dynamic from "next/dynamic";

/**
 * Loads the Clerk UI only when accounts are configured.
 *
 * `ssr: false` because the sign-in state is client-only: rendering it on the server would
 * either leak a signed-in shell to an anonymous visitor or flash the wrong state.
 */
const AuthButtons = dynamic(
  () => import("./auth-buttons").then((m) => m.AuthButtons),
  { ssr: false, loading: () => null },
);

export function AccountControls({
  enabled,
  onSignedIn,
}: {
  enabled: boolean;
  onSignedIn: () => void;
}) {
  if (!enabled) return null;
  return <AuthButtons onSignedIn={onSignedIn} />;
}
