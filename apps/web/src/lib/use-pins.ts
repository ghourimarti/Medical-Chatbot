"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Pinned conversations — PER-BROWSER, deliberately (F5.1).
 *
 * The honest version of this feature is a `pinned` column on the conversations table and a
 * field on the PATCH endpoint, so a pin follows the account to another device. That is
 * backend work, and this session is frontend-only. So pins live in localStorage.
 *
 * WHAT THAT COSTS, stated rather than hidden: a pin does not follow you to another device,
 * and clearing site data drops it. Nothing else in the app depends on it — a pin only
 * reorders the sidebar — so the failure mode is cosmetic, which is what makes the trade
 * acceptable here and would NOT make it acceptable for, say, a refusal category.
 *
 * THE SEAM: every consumer goes through `isPinned` / `togglePin` / `pinnedIds`. Swapping the
 * body of this hook for a call to `PATCH /api/v1/conversations/{id}` changes nothing above
 * it. The sidebar never touches localStorage directly, precisely so that swap stays a
 * one-file change.
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
