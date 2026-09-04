"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpenCheck, Check, Copy, RotateCcw, User } from "lucide-react";
import { cn } from "@/lib/utils";

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * The conversation itself — alternating turns (F4.1 rework).
 *
 * This REPLACES a bulleted timeline with a left border. That earlier treatment was an
 * accurate record and read as a changelog: it made the product look like a form that keeps
 * a log rather than something you talk to. Turn shape is what makes a conversation legible
 * at a glance — you should be able to tell who said what without reading a word.
 *
 * WHAT DOES NOT CHANGE, and it is the important part: past assistant turns are still
 * rendered WITHOUT the answer-kind treatments. `GET /api/v1/session/history` returns only
 * {role, content} — the database stores `kind` but the repository drops it on read. Giving
 * these bubbles the grounded/refused/emergency styling would mean GUESSING, and a past
 * emergency refusal redrawn as an ordinary answer is exactly the misrepresentation this UI
 * exists to prevent. A bubble is a LAYOUT; a kind treatment is a CLAIM. Only the live
 * answer, where the kind is known, gets the claim.
 */
export function Transcript({
  messages,
  onReask,
}: {
  messages: HistoryMessage[];
  onReask: (question: string) => void;
}) {
  if (messages.length === 0) return null;

  return (
    <section aria-label="Earlier in this session" className="space-y-6">
      {/* ONCE for the thread. Repeating it under every assistant turn turned a useful
          caveat into wallpaper — and on a long thread it was the most repeated sentence
          on the page. */}
      <p className="text-xs text-ink-muted">
        Earlier turns — sources are shown with the live answer.
      </p>
      {messages.map((m, i) =>
        m.role === "user" ? (
          <UserTurn key={i} content={m.content} onReask={onReask} />
        ) : (
          <AssistantTurn key={i} content={m.content} />
        ),
      )}
    </section>
  );
}

function UserTurn({ content, onReask }: { content: string; onReask: (q: string) => void }) {
  return (
    <div className="turn-enter flex justify-end gap-3">
      <div className="group flex max-w-[85%] flex-col items-end gap-1">
        <div className="rounded-3xl rounded-br-lg bg-surface-sunken px-4 py-2.5 text-ink">
          <p className="whitespace-pre-wrap text-[0.95rem] leading-relaxed">{content}</p>
        </div>
        {/* Re-asking is the one action a past QUESTION affords. Revealed on hover where
            hover exists, always present otherwise — a phone has no hover, and hiding it
            there would make it unreachable rather than tidy. */}
        <button
          onClick={() => onReask(content)}
          // The NAME carries the question. "Ask again" alone is what a screen-reader user
          // hears once per turn, identical every time, with no way to tell which question
          // it would re-ask — the visible text is adjacent, but the accessible name is not
          // allowed to depend on that. The e2e suite locates it by question text for the
          // same reason.
          aria-label={`Ask again: ${content}`}
          className={cn(
            "flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-ink-muted",
            "[@media(hover:hover)]:opacity-0 focus-visible:opacity-100 group-hover:opacity-100",
            "hover:text-ink",
          )}
        >
          <RotateCcw className="size-3" aria-hidden="true" />
          Ask again
        </button>
      </div>
      <span
        aria-hidden="true"
        className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-ink-muted"
      >
        <User className="size-3.5" />
      </span>
    </div>
  );
}

/**
 * One action in a turn's hover bar.
 *
 * Icon-only with an accessible name, the way this category does it — a row of words under
 * every answer competes with the answer. `title` gives sighted mouse users the same label
 * the screen reader already gets, so the icon is never a guess.
 */
function TurnAction({
  onClick,
  label,
  icon: Icon,
}: {
  onClick: () => void;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="rounded-md p-1.5 text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
    >
      <Icon className="size-3.5" />
    </button>
  );
}

function AssistantTurn({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      // Non-secure origin, or the document is not focused. Both are ordinary; saying
      // nothing is better than a false "Copied".
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2000);
  }, [content]);

  return (
    <div className="turn-enter group flex gap-3">
      {/* An avatar, so WHO IS SPEAKING is readable at a glance rather than inferred from
          alignment. The assistant mark is the same book icon the evidence block uses —
          the product's one visual claim is "this came from a source", so its avatar says
          that rather than being a generic bot face. */}
      <span
        aria-hidden="true"
        className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-wash text-accent"
      >
        <BookOpenCheck className="size-3.5" />
      </span>

      <div className="min-w-0 flex-1 space-y-1.5">
        {/* No bubble and no card: the assistant side is READING material, and a container
            around long medical prose fights the measure rather than helping it. */}
        <p className="answer-prose whitespace-pre-wrap text-ink">{content}</p>

        <div className="flex items-center gap-0.5 [@media(hover:hover)]:opacity-0 focus-within:opacity-100 group-hover:opacity-100">
          <TurnAction
            onClick={() => void copy()}
            label={copied ? "Copied" : "Copy this answer"}
            icon={copied ? Check : Copy}
          />
        </div>
      </div>
    </div>
  );
}
