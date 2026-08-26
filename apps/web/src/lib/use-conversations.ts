"use client";

import { useCallback, useEffect, useState } from "react";
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
      setItems((prev) => prev.filter((c) => c.id !== id));
      setActiveId((current) => (current === id ? null : current));
      return body.deleted_messages;
    },
    [],
  );

  const messages = useCallback(async (id: string) => {
    const res = await fetch(`/api/v1/conversations/${id}/messages`);
    if (!res.ok) return [];
    const body = (await res.json()) as { messages: { role: string; content: string }[] };
    return body.messages;
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
  };
}
