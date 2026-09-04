"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageSquare, MessageSquarePlus, Moon, Sun } from "lucide-react";
import { useRouter } from "next/navigation";
import { useConversationsContext } from "@/lib/conversations-context";
import { matches } from "@/lib/conversation-groups";
import { cn } from "@/lib/utils";

/**
 * Command palette — ⌘K / Ctrl-K (F5).
 *
 * Hand-rolled rather than pulled from a library: the whole surface is a filtered list and
 * a keydown handler, and `/` has ~23kB of headroom that PDF export and future work have a
 * better claim on than a dependency would.
 *
 * The list is deliberately SHORT and mixed — actions first, then threads — because a
 * palette that returns forty rows is a search box with extra steps. Threads are matched on
 * title only, the same honest limitation the sidebar filter carries: titles are user-set
 * and never auto-generated from the question, so a thread nobody named cannot be found by
 * what was asked in it. Fixing that needs a backend endpoint over stored messages.
 */

interface Item {
  id: string;
  label: string;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  run: () => void;
}

export function CommandPalette() {
  const convos = useConversationsContext();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const openerFocus = useRef<Element | null>(null);
  // Held in state, NOT read from `document` during render. This is a client component
  // but Next still server-renders it, and `document` does not exist there — reading it
  // in the useMemo below would throw during SSR for the sake of choosing an icon.
  const [isDark, setIsDark] = useState(false);

  const toggleTheme = useCallback(() => {
    const root = document.documentElement;
    const isDark =
      root.dataset.theme === "dark" ||
      (!root.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = isDark ? "light" : "dark";
    root.dataset.theme = next;
    try {
      window.localStorage.setItem("medbot.theme", next);
    } catch {
      /* in-memory for this session; the toggle still works */
    }
  }, []);

  const items = useMemo<Item[]>(() => {
    const actions: Item[] = [
      {
        id: "new",
        label: "New chat",
        icon: MessageSquarePlus,
        run: () => {
          void convos.create().then((c) => router.push(c ? `/chat/${c.id}` : "/chat"));
        },
      },
      {
        id: "theme",
        label: "Toggle light / dark theme",
        icon: isDark ? Sun : Moon,
        run: toggleTheme,
      },
    ];
    const threads: Item[] = convos.items
      .filter((c) => matches(c, query))
      .slice(0, 6)
      .map((c) => ({
        id: c.id,
        label: c.title ?? "Untitled conversation",
        hint: "conversation",
        icon: MessageSquare,
        run: () => {
          convos.setActiveId(c.id);
          router.push(`/chat/${c.id}`);
        },
      }));
    const q = query.trim().toLowerCase();
    return [...actions.filter((a) => !q || a.label.toLowerCase().includes(q)), ...threads];
  }, [convos, query, toggleTheme, isDark, router]);

  // Global shortcut, bound to the WINDOW so it works wherever focus is — including
  // inside the question box, which is deliberate and matches every product that has one:
  // ⌘K is how you leave what you are doing, so making it inert in a text field would
  // defeat it. preventDefault stops the browser claiming the chord for its own search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openerFocus.current = document.activeElement;
        setOpen((v) => !v);
        setQuery("");
        setActive(0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    setIsDark(
      root.dataset.theme === "dark" ||
        (!root.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches),
    );
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
    // Focus goes back where it came from. A palette that dumps you at the top of the
    // document on close is the same defect as a drawer that does it.
    else if (openerFocus.current instanceof HTMLElement) openerFocus.current.focus();
  }, [open]);

  if (!open) return null;

  const choose = (item: Item | undefined) => {
    if (!item) return;
    item.run();
    setOpen(false);
  };

  return (
    <div
      className="fixed inset-0 flex items-start justify-center p-4 pt-[12vh]"
      style={{ zIndex: "var(--z-palette)" }}
    >
      <button
        aria-label="Close command palette"
        onClick={() => setOpen(false)}
        className="fixed inset-0 bg-[var(--scrim)]"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative w-full max-w-lg overflow-hidden rounded-xl border border-line bg-surface-raised shadow-[var(--shadow-lg)]"
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((i) => Math.min(i + 1, items.length - 1));
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((i) => Math.max(i - 1, 0));
            }
            if (e.key === "Enter") {
              e.preventDefault();
              choose(items[active]);
            }
          }}
          placeholder="Jump to a conversation, or run a command…"
          aria-label="Command palette search"
          className="w-full border-b border-line bg-transparent px-4 py-3 text-sm outline-none placeholder:text-ink-muted"
        />

        <ul className="max-h-80 overflow-y-auto p-1.5">
          {items.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-ink-muted">
              Nothing matches “{query}”. Conversations are matched on the title you gave
              them, not on what was asked inside them.
            </li>
          ) : (
            items.map((item, i) => {
              const Icon = item.icon;
              return (
                <li key={item.id}>
                  <button
                    onClick={() => choose(item)}
                    onMouseEnter={() => setActive(i)}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm",
                      i === active ? "bg-accent-wash text-ink" : "text-ink-muted",
                    )}
                  >
                    <Icon className="size-3.5 shrink-0" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.hint && <span className="text-xs text-ink-muted">{item.hint}</span>}
                  </button>
                </li>
              );
            })
          )}
        </ul>
      </div>
    </div>
  );
}
