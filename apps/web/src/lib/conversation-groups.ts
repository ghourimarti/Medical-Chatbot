import type { Conversation } from "@/lib/contract";

/**
 * Sidebar ordering: pinned first, then recency buckets (F3.4).
 *
 * Pure functions, no React, no Date.now() reached for internally — `now` is a parameter so
 * the bucket boundaries can be tested without freezing the clock or waiting for midnight.
 * "Today" is a calendar boundary, not a rolling 24 hours: something asked at 23:50 should
 * read as "Yesterday" at 00:10, not sit under Today for another day.
 */

export type GroupLabel = "Pinned" | "Today" | "Yesterday" | "Previous 7 days" | "Older";

export interface ConversationGroup {
  label: GroupLabel;
  items: Conversation[];
}

const ORDER: GroupLabel[] = ["Pinned", "Today", "Yesterday", "Previous 7 days", "Older"];

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function bucketFor(updatedAt: string, now: Date): Exclude<GroupLabel, "Pinned"> {
  const t = new Date(updatedAt).getTime();
  // An unparseable timestamp sorts to Older rather than throwing. A malformed date from the
  // API should cost a thread its bucket, never the whole sidebar.
  if (Number.isNaN(t)) return "Older";

  const today = startOfDay(now);
  const day = 86_400_000;
  if (t >= today) return "Today";
  if (t >= today - day) return "Yesterday";
  if (t >= today - 7 * day) return "Previous 7 days";
  return "Older";
}

/**
 * Case-insensitive substring match over the TITLE only.
 *
 * Deliberately not message text: searching what people actually asked requires a backend
 * endpoint over the stored messages, and inventing a client-side approximation would mean
 * shipping a search box that silently misses most of what a user is looking for. A title
 * filter that is honest about being a title filter is the better half-step — the input is
 * labelled "Filter by title" for exactly this reason.
 *
 * An untitled thread matches only the empty query, so filtering never makes a thread the
 * user cannot otherwise reach appear under an unrelated term.
 */
export function matches(c: Conversation, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (c.title ?? "").toLowerCase().includes(q);
}

export function groupConversations(
  items: Conversation[],
  { pinnedIds, query, now }: { pinnedIds: string[]; query: string; now: Date },
): ConversationGroup[] {
  const pinned = new Set(pinnedIds);
  const buckets = new Map<GroupLabel, Conversation[]>();

  for (const c of items) {
    if (!matches(c, query)) continue;
    const label: GroupLabel = pinned.has(c.id) ? "Pinned" : bucketFor(c.updated_at, now);
    const list = buckets.get(label);
    if (list) list.push(c);
    else buckets.set(label, [c]);
  }

  for (const list of buckets.values()) {
    list.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  }

  return ORDER.filter((l) => buckets.get(l)?.length).map((label) => ({
    label,
    items: buckets.get(label) ?? [],
  }));
}
