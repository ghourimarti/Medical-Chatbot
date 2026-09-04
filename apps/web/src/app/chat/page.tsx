"use client";

import { ChatSurface } from "@/components/chat/chat-surface";

/**
 * /chat — the app with no thread selected yet.
 *
 * Asking here creates a conversation and the surface navigates to /chat/<id>, so the very
 * first question already has an addressable home. Nothing lives at this route except that
 * one decision; the surface itself is shared with /chat/[id].
 */
export default function ChatPage() {
  return <ChatSurface />;
}
