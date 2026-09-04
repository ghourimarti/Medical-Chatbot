"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Check, FileDown, MessageSquarePlus, Pencil, Pin, PinOff, Search, Settings, Trash2, X,
} from "lucide-react";
import type { Conversation } from "@/lib/contract";
import { Button } from "@/components/ui/button";
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
  const router = useRouter();
  const { pinnedIds, isPinned, togglePin } = usePins();
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Server search results. `null` means "no server search available", which is NOT the
  // same as "no matches" — the empty state below says something different for each.
  const [results, setResults] = useState<Conversation[] | null>(null);
  const [serverSearch, setServerSearch] = useState(true);
  const [pinOnServer, setPinOnServer] = useState(true);

  // Debounced server search. 220ms: long enough that typing a word is one request rather
  // than six, short enough that the list does not feel like it lags behind the keyboard.
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults(null);
      return;
    }
    let stale = false;
    const t = setTimeout(() => {
      void convos.search(q).then((rows) => {
        if (stale) return;
        // null => the endpoint is not there. Fall back to filtering titles locally and
        // SAY SO, rather than reporting "no matches" for a search that never happened.
        setServerSearch(rows !== null);
        setResults(rows);
      });
    }, 220);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [query, convos]);

  // `new Date()` is read at render rather than held in state: the buckets only need to be
  // right when the list is drawn, and a ticking clock here would re-render the sidebar
  // every second for a boundary that moves once a day.
  const groups = useMemo(() => {
    // When the server answered, IT decided what matches — so the local title filter must
    // be switched off, or a thread found by its message text would be filtered straight
    // back out again for not having the word in its title.
    const source = results ?? convos.items;
    const localFilter = results === null ? query : "";
    // Server `pinned` wins; the localStorage set is only consulted when the API has no
    // pinning to report.
    const serverPinned = source.filter((c) => c.pinned).map((c) => c.id);
    const effectivePins = pinOnServer ? serverPinned : pinnedIds;
    return groupConversations(source, {
      pinnedIds: effectivePins,
      query: localFilter,
      now: new Date(),
    });
  }, [convos.items, results, pinnedIds, pinOnServer, query]);

  const unclaimed = convos.items.some((c) => !c.claimed);
  const matched = groups.reduce((n, g) => n + g.items.length, 0);

  if (collapsed) {
    // Icon rail. Deliberately NOT a squeezed version of the full list: truncated titles at
    // 3.5rem are unreadable, so the collapsed state offers the one action worth having.
    return (
      <nav aria-label="Saved conversations" className="flex flex-1 flex-col items-center gap-2 py-3">
        <button
          onClick={() => {
            void convos.create().then((c) => router.push(c ? `/chat/${c.id}` : "/chat"));
          }}
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
      // rail-content fades and slides the CONTENTS while the rail animates its width.
      // Without it the labels sat at full width inside a 3.5rem box for a frame on
      // collapse, which reads as a flicker instead of a fold.
      className="rail-content flex flex-1 flex-col overflow-hidden"
      data-collapsed="false"
    >
      <div className="space-y-2.5 p-3.5">
        {/* The PRIMARY action of the whole sidebar, sized like one. It was a 32px
            secondary button indistinguishable from the filter beneath it — measured
            against every product in this category, which gives it ~48px, a full pill and
            an accent tint. Size IS hierarchy; a primary action that matches its
            neighbours has no hierarchy to communicate. */}
        <button
          onClick={() => {
            // Navigate to the NEW thread's own URL, so it is refreshable and linkable the
            // moment it exists. Pushing the bare /chat would have created a conversation
            // and then left the address bar pointing at "no thread selected".
            void convos.create().then((c) => router.push(c ? `/chat/${c.id}` : "/chat"));
            onNavigate?.();
          }}
          className="flex h-11 w-full items-center gap-2.5 rounded-full border border-accent/25 bg-accent-wash px-4 text-[0.9375rem] font-medium text-accent transition-colors hover:border-accent/40 hover:bg-accent/10"
        >
          <MessageSquarePlus className="size-4" aria-hidden="true" />
          New chat
        </button>

        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted"
            aria-hidden="true"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            // "Search" again, and now it IS one: S22 added an endpoint that matches
            // message text as well as titles. The label tracks the capability — it said
            // "Filter by title" for as long as that was the truth, and changes back
            // automatically below if the server cannot search.
            placeholder={serverSearch ? "Search conversations" : "Filter by title"}
            aria-label={
              serverSearch ? "Search conversations" : "Filter conversations by title"
            }
            className="h-10 w-full rounded-full border border-line bg-surface-raised pl-9 pr-3 text-sm placeholder:text-ink-muted focus:border-line-strong"
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
          <p className="px-3.5 py-2 text-sm leading-relaxed text-ink-muted">
            {serverSearch ? (
              <>Nothing matches “{query}” in your conversations.</>
            ) : (
              <>
                No conversation <em>title</em> matches “{query}”. Search is unavailable, so
                only titles were checked — and titles are set by you, so a thread you never
                named will not appear here.
              </>
            )}
          </p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mb-4">
              <h2 className="px-3.5 pb-1.5 pt-1 text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-muted uppercase">
                {group.label}
              </h2>
              <ul className="space-y-0.5">
                {group.items.map((c) => {
                  const active = c.id === convos.activeId;
                  const editing = c.id === editingId;
                  const pinned = pinOnServer ? Boolean(c.pinned) : isPinned(c.id);
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
                            // A full pill with an accent tint, not a faint rectangle.
                            // "Which conversation am I in" is the question this sidebar
                            // exists to answer, and it was answered in a shade barely
                            // distinguishable from the surface behind it.
                            "group flex items-center rounded-full transition-colors",
                            active
                              ? "bg-accent-wash text-ink"
                              : "hover:bg-surface-raised",
                          )}
                        >
                          <button
                            onClick={() => {
                              convos.setActiveId(c.id);
                              router.push(`/chat/${c.id}`);
                              onNavigate?.();
                            }}
                            aria-current={active ? "true" : undefined}
                            className={cn(
                              "min-w-0 flex-1 truncate px-3.5 py-2 text-left text-sm",
                              "transition-colors duration-150",
                              active ? "font-medium text-accent" : "text-ink-muted group-hover:text-ink",
                            )}
                          >
                            {label}
                          </button>

                          {/* Reveal-on-hover ONLY where hover exists.
                              `opacity-0 group-hover:opacity-100` is the standard idiom and
                              it is broken on touch: a phone has no hover, so pin, rename,
                              delete and print were permanently invisible — the entire
                              management surface unreachable on the device most people
                              would use. The old sidebar had them always visible; this was
                              a regression my "polish" introduced, caught by the mobile
                              project. `@media(hover:hover)` scopes the hiding to pointers
                              that can actually reveal it again, and focus-within keeps it
                              reachable by keyboard on those. */}
                          <div className="flex shrink-0 items-center [@media(hover:hover)]:opacity-0 focus-within:opacity-100 group-hover:opacity-100">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                const next = !pinned;
                                void convos.setPinned(c.id, next).then((ok) => {
                                  // The server has no pinning. Remember that, flip the
                                  // local pin instead, and keep the control working.
                                  if (!ok) {
                                    setPinOnServer(false);
                                    togglePin(c.id);
                                  }
                                });
                              }}
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
