"use client";

import { use } from "react";
import { ChatSurface } from "@/components/chat/chat-surface";

/**
 * /chat/<id> — a conversation you can refresh, bookmark and link to.
 *
 * The id in the URL is the source of truth for which thread is open. Before this route
 * existed, conversation identity lived only in React state: a refresh lost the thread and
 * the next question quietly started a new one, which is what "it navigates me towards the
 * old conversation" actually was.
 *
 * `params` is a promise in Next 15, unwrapped with `use()`.
 */
export default function ChatThreadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ChatSurface conversationId={id} />;
}
