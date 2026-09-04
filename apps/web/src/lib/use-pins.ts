"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Pinned conversations — the LOCAL FALLBACK (S22).
 *
 * Pinning is now a `pinned` column and a PATCH field, so a pin follows the account to
 * another device. This hook is what happens when that server support is NOT there: the
 * sidebar tries the API first and falls back here when the call reports it is unsupported.
 *
 * WHY KEEP IT AT ALL rather than deleting it now the real thing exists. It is what makes
 * the backend half of S22 revertable on its own. Roll the API back and the sidebar keeps
 * pinning — per-browser, degraded, but working — instead of presenting a control that
 * silently does nothing. A feature that fails by getting smaller is a very different thing
 * from one that fails by lying.
 *
 * The cost, stated: a local pin does not follow you to another device and clearing site
 * data drops it. Acceptable because a pin only reorders a list.
 */

const KEY = "medbot.pinned";

function read(): string[] {
  // Reads are wrapped because a private window, disabled site data, or a thumbnail
  // capture can make localStorage THROW on access, not merely return null.
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function usePins() {
  // Starts empty on BOTH server and first client render, then fills in an effect. Reading
  // localStorage during render would make the server and client markup disagree and trip
  // hydration — the same reason PreferencesScript runs before React rather than inside it.
  const [pinned, setPinned] = useState<string[]>([]);

  useEffect(() => {
    setPinned(read());
  }, []);

  const togglePin = useCallback((id: string) => {
    setPinned((prev) => {
      const next = prev.includes(id) ? prev.filter((p) => p !== id) : [id, ...prev];
      try {
        window.localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        // Persisting failed (quota, private mode). The in-memory pin still works for this
        // session; silently degrading beats refusing to pin at all.
      }
      return next;
    });
  }, []);

  const isPinned = useCallback((id: string) => pinned.includes(id), [pinned]);

  return { pinnedIds: pinned, isPinned, togglePin };
}
