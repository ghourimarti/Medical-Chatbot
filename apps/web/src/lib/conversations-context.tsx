"use client";

import { createContext, useContext, useMemo } from "react";
import { useConversations } from "@/lib/use-conversations";

/**
 * Conversation state, hoisted to the layout (F3).
 *
 * WHY THIS EXISTS AT ALL: the sidebar used to live inside `page.tsx`, so `useConversations`
 * could be a plain hook called in one place. Moving the sidebar into the root layout — which
 * is what makes it persist across routes and stop reading as a panel bolted onto one page —
 * puts the list and the chat surface in two different subtrees. Two calls to the hook would
 * mean two independent copies of the list: renaming a thread in the sidebar would not update
 * the header above the transcript, and creating one from the chat surface would not appear
 * in the list until a refetch.
 *
 * So the hook is UNCHANGED and simply lifted. Same fetches, same optimistic-update policy,
 * same anonymous-first behaviour — one instance, shared. That is deliberately the smallest
 * change that makes a persistent shell possible.
 */

type ConversationsValue = ReturnType<typeof useConversations>;

const Ctx = createContext<ConversationsValue | null>(null);

export function ConversationsProvider({ children }: { children: React.ReactNode }) {
  const {
    items, enabled, signedIn, activeId, loading,
    setActiveId, refresh, create, rename, remove, messages, claim, setPinned, search,
  } = useConversations();

  // Memoised on the ACTUAL values, not on the hook's return object — that object is a new
  // literal every render, so `useMemo(() => value, [value])` would recompute every time and
  // buy nothing. The mutators are already useCallback-stable inside the hook, so in practice
  // this only changes identity when the list, the active thread, or a flag really changes.
  // It matters because every consumer re-renders on a new identity, and one of those
  // consumers is the transcript while tokens are streaming into it.
  const value = useMemo(
    () => ({
      items, enabled, signedIn, activeId, loading,
      setActiveId, refresh, create, rename, remove, messages, claim, setPinned, search,
    }),
    [items, enabled, signedIn, activeId, loading,
     setActiveId, refresh, create, rename, remove, messages, claim, setPinned, search],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useConversationsContext(): ConversationsValue {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useConversationsContext must be used inside <ConversationsProvider>");
  }
  return ctx;
}
