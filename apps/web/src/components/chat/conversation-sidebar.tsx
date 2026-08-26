"use client";

import { useState } from "react";
import { Check, MessageSquarePlus, Pencil, Trash2, X } from "lucide-react";
import type { Conversation } from "@/lib/contract";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Saved-thread sidebar (S21).
 *
 * Shown to ANONYMOUS visitors too — threads are owned by the session cookie until an
 * account claims them. A sidebar gated behind sign-up would put a wall in front of the
 * core value, which D24 explicitly forbids.
 *
 * Titles come from the user, never from the question. Auto-titling a thread with its first
 * medical question means "Chest pain at night" sits in a list that a partner, a colleague,
 * or anyone glancing at the screen can read. The default is deliberately neutral.
 */
export function ConversationSidebar({
  items,
  activeId,
  signedIn,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}: {
  items: Conversation[];
  activeId: string | null;
  signedIn: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const unclaimed = items.some((c) => !c.claimed);

  return (
    <nav aria-label="Saved conversations" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xs font-medium tracking-wide text-ink-muted uppercase">
          Conversations
        </h2>
        <Button variant="ghost" size="sm" onClick={onCreate} aria-label="New conversation">
          <MessageSquarePlus className="size-3.5" aria-hidden="true" />
          New
        </Button>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No saved conversations yet. Start one to keep a thread of related questions
          together.
        </p>
      ) : (
        <ul className="space-y-1">
          {items.map((c) => {
            const active = c.id === activeId;
            const editing = c.id === editingId;
            const confirming = c.id === confirmId;

            return (
              <li key={c.id}>
                {editing ? (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (draft.trim()) onRename(c.id, draft.trim());
                      setEditingId(null);
                    }}
                    className="flex items-center gap-1"
                  >
                    <input
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => e.key === "Escape" && setEditingId(null)}
                      maxLength={200}
                      aria-label="Conversation title"
                      className="min-w-0 flex-1 rounded border border-line-strong bg-surface-raised px-2 py-1 text-sm"
                    />
                    <Button type="submit" variant="ghost" size="sm" aria-label="Save title">
                      <Check className="size-3.5" aria-hidden="true" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setEditingId(null)}
                      aria-label="Cancel rename"
                    >
                      <X className="size-3.5" aria-hidden="true" />
                    </Button>
                  </form>
                ) : (
                  <div
                    className={cn(
                      "group flex items-center gap-1 rounded-md",
                      active && "bg-accent-wash",
                    )}
                  >
                    <button
                      onClick={() => onSelect(c.id)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm",
                        active ? "font-medium text-ink" : "text-ink-muted hover:text-ink",
                      )}
                    >
                      {c.title ?? "Untitled conversation"}
                    </button>

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setDraft(c.title ?? "");
                        setEditingId(c.id);
                      }}
                      aria-label={`Rename ${c.title ?? "untitled conversation"}`}
                    >
                      <Pencil className="size-3.5" aria-hidden="true" />
                    </Button>

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmId(c.id)}
                      aria-label={`Delete ${c.title ?? "untitled conversation"}`}
                    >
                      {/* Not a red button: red is reserved for medical emergencies (D27). */}
                      <Trash2 className="size-3.5" aria-hidden="true" />
                    </Button>
                  </div>
                )}

                {confirming && (
                  <div className="mt-1 space-y-1 rounded-md border border-line bg-surface-sunken p-2">
                    <p className="text-xs text-ink">
                      Delete this conversation and every question in it?
                    </p>
                    <div className="flex gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          onDelete(c.id);
                          setConfirmId(null);
                        }}
                      >
                        Delete
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setConfirmId(null)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {unclaimed && !signedIn && (
        // Says what signing in DOES, rather than dangling a generic prompt. Someone who has
        // typed health questions deserves to know their threads are kept, not replaced.
        <p className="rounded-md bg-surface-sunken px-2 py-1.5 text-xs text-ink-muted">
          These conversations are saved to this browser. Sign in to keep them across devices.
        </p>
      )}
    </nav>
  );
}
