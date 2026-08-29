"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Check, FileDown, MessageSquarePlus, Pencil, Pin, PinOff, Search, Settings, Trash2, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AccountControls } from "@/components/auth/account-controls";
import { useConversationsContext } from "@/lib/conversations-context";
import { groupConversations } from "@/lib/conversation-groups";
import { SettingsPanel } from "@/components/shell/settings-panel";
import { usePins } from "@/lib/use-pins";
import { cn } from "@/lib/utils";

/**
 * Sidebar contents (F1/F3). Route-agnostic: it renders the same in the desktop rail and
 * inside the mobile drawer, which is why it takes `collapsed` and `onNavigate` rather
 * than reaching for a media query of its own.
 *
 * Titles still come from the user, never auto-generated from the question (S21). Auto-
 * titling a thread "Chest pain at night" puts a health disclosure in a list that a
 * partner, a colleague or a shoulder-surfer can read. That decision is what makes the
 * filter below weak — most threads are "Untitled" — and the input is labelled honestly
 * because of it.
 */
export function Sidebar({
  collapsed = false,
  onToggleCollapsed,
  onNavigate,
}: {
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onNavigate?: () => void;
}) {
  const convos = useConversationsContext();
  const { pinnedIds, isPinned, togglePin } = usePins();
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // `new Date()` is read at render rather than held in state: the buckets only need to be
  // right when the list is drawn, and a ticking clock here would re-render the sidebar
  // every second for a boundary that moves once a day.
  const groups = useMemo(
    () => groupConversations(convos.items, { pinnedIds, query, now: new Date() }),
    [convos.items, pinnedIds, query],
  );

  const unclaimed = convos.items.some((c) => !c.claimed);
  const matched = groups.reduce((n, g) => n + g.items.length, 0);

  if (collapsed) {
    // Icon rail. Deliberately NOT a squeezed version of the full list: truncated titles at
    // 3.5rem are unreadable, so the collapsed state offers the one action worth having.
    return (
      <nav aria-label="Saved conversations" className="flex flex-1 flex-col items-center gap-2 py-3">
        <button
          onClick={() => void convos.create()}
          aria-label="New conversation"
          className="rounded-md p-2 text-ink-muted hover:bg-surface-raised hover:text-ink"
        >
          <MessageSquarePlus className="size-4" aria-hidden="true" />
        </button>
        <button
          onClick={onToggleCollapsed}
          aria-label="Expand sidebar to search conversations"
          className="rounded-md p-2 text-ink-muted hover:bg-surface-raised hover:text-ink"
        >
          <Search className="size-4" aria-hidden="true" />
        </button>
        <div className="mt-auto">
          <button
            onClick={() => setSettingsOpen(true)}
            aria-label="Settings"
            className="block rounded-md p-2 text-ink-muted hover:bg-surface-raised hover:text-ink"
          >
            <Settings className="size-4" aria-hidden="true" />
          </button>
          <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </div>
      </nav>
    );
  }

  return (
    // ONE navigation landmark for the whole sidebar, not just the list.
    //
    // The list alone used to carry the label, which put "New chat", the filter and the
    // account controls OUTSIDE the region a screen-reader user lands in when they jump to
    // navigation — so the only way to CREATE a thread sat outside the region for managing
    // threads. The e2e suite scopes every sidebar assertion to this landmark and caught it
    // immediately, which is the landmark earning its keep rather than a test being fussy.
    <nav
      aria-label="Saved conversations"
      className="flex flex-1 flex-col overflow-hidden"
    >
      <div className="space-y-2 p-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void convos.create();
            onNavigate?.();
          }}
          className="w-full justify-start"
        >
          <MessageSquarePlus className="size-3.5" aria-hidden="true" />
          New chat
        </Button>

        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-ink-muted"
            aria-hidden="true"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            // "Filter by title", NOT "Search". Searching what people actually ASKED needs a
            // backend endpoint over stored messages; this only matches titles. A box
            // labelled "Search" that silently misses every question body would be a lie.
            placeholder="Filter by title"
            aria-label="Filter conversations by title"
            className="w-full rounded-md border border-line bg-surface-raised py-1.5 pl-7 pr-2 text-sm placeholder:text-ink-muted"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {!convos.enabled ? null : convos.items.length === 0 ? (
          <p className="px-1 py-2 text-sm text-ink-muted">
            No saved conversations yet. Start one to keep a thread of related questions
            together.
          </p>
        ) : matched === 0 ? (
          <p className="px-1 py-2 text-sm text-ink-muted">
            No conversation title matches “{query}”. Titles are set by you, so a thread you
            never named will not appear here.
          </p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mb-3">
              <h2 className="px-1 pb-1 text-xs font-medium tracking-wide text-ink-muted uppercase">
                {group.label}
              </h2>
              <ul className="space-y-0.5">
                {group.items.map((c) => {
                  const active = c.id === convos.activeId;
                  const editing = c.id === editingId;
                  const pinned = isPinned(c.id);
                  const label = c.title ?? "Untitled conversation";

                  return (
                    <li key={c.id}>
                      {editing ? (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            if (draft.trim()) convos.rename(c.id, draft.trim());
                            setEditingId(null);
                          }}
                          className="flex items-center gap-1 px-1"
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
                            "group flex items-center rounded-md",
                            active && "bg-accent-wash",
                          )}
                        >
                          <button
                            onClick={() => {
                              convos.setActiveId(c.id);
                              onNavigate?.();
                            }}
                            aria-current={active ? "true" : undefined}
                            className={cn(
                              "min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm",
                              active ? "font-medium text-ink" : "text-ink-muted hover:text-ink",
                            )}
                          >
                            {label}
                          </button>

                          {/* Row actions stay reachable by KEYBOARD at all times. A common
                              pattern here is `opacity-0 group-hover:opacity-100`, which
                              hides them from anyone not using a mouse. */}
                          <div className="flex shrink-0 items-center opacity-0 focus-within:opacity-100 group-hover:opacity-100">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => togglePin(c.id)}
                              aria-label={`${pinned ? "Unpin" : "Pin"} ${label}`}
                              aria-pressed={pinned}
                            >
                              {pinned ? (
                                <PinOff className="size-3.5" aria-hidden="true" />
                              ) : (
                                <Pin className="size-3.5" aria-hidden="true" />
                              )}
                            </Button>
                            {/* Select THEN print, and the order matters: printing renders
                                what is on screen, so the transcript for this thread has to
                                be loaded first. The page listens for this event and prints
                                once its messages have painted — dispatching and printing
                                here would reliably print the PREVIOUS conversation. */}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                convos.setActiveId(c.id);
                                window.dispatchEvent(
                                  new CustomEvent("medbot:print-conversation", { detail: c.id }),
                                );
                                onNavigate?.();
                              }}
                              aria-label={`Print ${label}`}
                            >
                              <FileDown className="size-3.5" aria-hidden="true" />
                            </Button>

                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setDraft(c.title ?? "");
                                setEditingId(c.id);
                              }}
                              aria-label={`Rename ${label}`}
                            >
                              <Pencil className="size-3.5" aria-hidden="true" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setConfirmId(c.id)}
                              aria-label={`Delete ${label}`}
                            >
                              {/* Not red: red is reserved for medical emergencies (D27). */}
                              <Trash2 className="size-3.5" aria-hidden="true" />
                            </Button>
                          </div>
                        </div>
                      )}

                      {confirmId === c.id && (
                        <div className="mt-1 space-y-1 rounded-md border border-line bg-surface-raised p-2">
                          <p className="text-xs text-ink">
                            Delete this conversation and every question in it?
                          </p>
                          <div className="flex gap-1">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                void convos.remove(c.id);
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
            </section>
          ))
        )}
      </div>

      <div className="space-y-2 border-t border-line p-3">
        {unclaimed && !convos.signedIn && (
          <p className="rounded-md bg-surface-raised px-2 py-1.5 text-xs text-ink-muted">
            {/* States the consequence for work ALREADY DONE, rather than a generic
                "Sign up!". Someone who has typed health questions deserves to know the
                threads are kept, not replaced. */}
            These conversations are saved to this browser. Sign in to keep them across
            devices.
          </p>
        )}
        {/* Clerk is OPTIONAL (D24): with no publishable key this renders nothing, and
            the sidebar stays fully usable anonymously. `claim` on sign-in is what stops
            someone's existing threads being stranded by creating an account. */}
        <AccountControls
          enabled={Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)}
          onSignedIn={() => void convos.claim()}
        />
        {/* A BUTTON that opens settings, not a link to a prose page wearing a gear icon.
            The previous version sent anyone looking for the theme control to
            /how-it-works, where they would reasonably conclude there were no settings. */}
        <button
          onClick={() => setSettingsOpen(true)}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-ink-muted hover:bg-surface-raised hover:text-ink"
        >
          <Settings className="size-3.5" aria-hidden="true" />
          Settings
        </button>
        <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </div>
    </nav>
  );
}
