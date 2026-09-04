"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Conversation, ConversationList } from "@/lib/contract";

/**
 * Saved threads (S21).
 *
 * Works WITHOUT an account. The API owns a conversation by user_id when signed in and by
 * the anonymous session cookie otherwise, so the sidebar is useful before anyone signs up —
 * which is the whole point of D24's anonymous-first sequencing. Signing in later calls
 * `claim`, which binds the anonymous threads to the account instead of stranding them.
 */
export function useConversations() {
  const [items, setItems] = useState<Conversation[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  /**
   * Conversations THIS client deleted. Fetching one again can only ever 404.
   *
   * `remove` already clears activeId, but that is not sufficient: other components hold
   * the id in their own effects and closures, and their requests are issued before the
   * state update reaches them. A real deletion produced SIX `GET /messages` for the dead
   * id across 1.3s - two within 20ms of the DELETE, four more a second later. Each one
   * increments `medbot_errors_total`, so the app manufactured its own error rate and the
   * audit's "errors == 0" gate failed on a conversation the user had chosen to destroy.
   *
   * Guarding at the DATA layer rather than in one component makes the invariant hold no
   * matter which render path still has the id: deleted means unfetchable, full stop.
   * A ref, not state, because changing it must not re-render anything.
   */
  const deletedIds = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/conversations");
      if (!res.ok) {
        // `enabled: false` means no database is configured — the feature is ABSENT, not
        // broken, and the sidebar hides rather than showing an error for something the
        // deployment simply does not offer.
        setEnabled(false);
        return;
      }
      const body = (await res.json()) as ConversationList;
      setEnabled(body.enabled);
      setSignedIn(body.signed_in);
      setItems(body.conversations);
    } catch {
      setEnabled(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (title?: string): Promise<Conversation | null> => {
      const res = await fetch("/api/v1/conversations", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: title ?? null }),
      });
      if (!res.ok) return null;
      const convo = (await res.json()) as Conversation;
      setItems((prev) => [convo, ...prev]);
      setActiveId(convo.id);
      return convo;
    },
    [],
  );

  const rename = useCallback(async (id: string, title: string) => {
    // Optimistic: renaming is trivially reversible and a round-trip of latency for a text
    // edit feels broken. A failure refreshes back to the server's truth.
    setItems((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    const res = await fetch(`/api/v1/conversations/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!res.ok) await refresh();
  }, [refresh]);

  const remove = useCallback(
    async (id: string): Promise<number | null> => {
      // NOT optimistic. This destroys stored health questions, so the UI must not claim it
      // happened until the server says how many rows went — the same standard as
      // delete-my-data (S10.8).
      const res = await fetch(`/api/v1/conversations/${id}`, { method: "DELETE" });
      if (!res.ok) return null;
      const body = (await res.json()) as { deleted_messages: number };
      deletedIds.current.add(id);
      setItems((prev) => prev.filter((c) => c.id !== id));
      setActiveId((current) => (current === id ? null : current));
      return body.deleted_messages;
    },
    [],
  );

  const messages = useCallback(async (id: string) => {
    // A thread this client deleted is gone by definition; asking the server can only
    // produce a 404 that pollutes the error metric. Empty is the honest answer.
    if (deletedIds.current.has(id)) return [];
    const res = await fetch(`/api/v1/conversations/${id}/messages`);
    if (!res.ok) return [];
    const body = (await res.json()) as { messages: { role: string; content: string }[] };
    return body.messages;
  }, []);

  /**
   * Set or clear a pin. S22.
   *
   * Optimistic, like rename: a pin is trivially reversible and a round-trip of latency for
   * a toggle feels broken. A failure refreshes back to the server's truth.
   *
   * Returns FALSE when the server does not support pinning, which is the seam that lets the
   * backend half of this change be reverted on its own: the caller falls back to a
   * per-browser pin instead of the feature silently doing nothing.
   */
  const setPinned = useCallback(
    async (id: string, pinned: boolean): Promise<boolean> => {
      setItems((prev) => prev.map((c) => (c.id === id ? { ...c, pinned } : c)));
      try {
        const res = await fetch(`/api/v1/conversations/${id}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ pinned }),
        });
        if (!res.ok) {
          await refresh();
          return false;
        }
        return true;
      } catch {
        await refresh();
        return false;
      }
    },
    [refresh],
  );

  /**
   * Search titles AND message text, server-side. S22.
   *
   * Returns NULL — not [] — when the endpoint is unavailable. The distinction is the whole
   * point: [] means "searched, found nothing" and null means "could not search", and the
   * sidebar shows completely different things for those two. Collapsing them would tell a
   * user their conversation does not exist when in fact the server could not look.
   */
  const search = useCallback(async (query: string): Promise<Conversation[] | null> => {
    const q = query.trim();
    if (!q) return [];
    try {
      const res = await fetch(`/api/v1/conversations/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) return null;
      const body = (await res.json()) as { conversations: Conversation[] };
      return body.conversations ?? [];
    } catch {
      return null;
    }
  }, []);

  /** Called immediately after sign-in. The session id comes from the cookie server-side,
   *  so a caller cannot claim a session they do not hold. */
  const claim = useCallback(async () => {
    const res = await fetch("/api/v1/auth/claim", { method: "POST" });
    if (res.ok) await refresh();
  }, [refresh]);

  return {
    items,
    enabled,
    signedIn,
    activeId,
    loading,
    setActiveId,
    refresh,
    create,
    rename,
    remove,
    messages,
    claim,
    setPinned,
    search,
  };
}
