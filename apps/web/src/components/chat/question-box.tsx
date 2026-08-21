"use client";

import { useState } from "react";
import { CornerDownLeft, Search, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Mirrors QueryRequest.question (min_length=1, max_length=2000). Enforced client-side so
 *  an over-long question is caught before a round-trip, and server-side because a client
 *  constraint is a courtesy, never a control. */
const MAX_LENGTH = 2000;

export function QuestionBox({
  onSubmit,
  onCancel,
  busy,
  autoFocus = false,
}: {
  onSubmit: (question: string) => void;
  onCancel: () => void;
  busy: boolean;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState("");
  const remaining = MAX_LENGTH - value.length;
  const tooLong = remaining < 0;
  const canSubmit = value.trim().length > 0 && !tooLong && !busy;

  function submit() {
    if (!canSubmit) return;
    onSubmit(value);
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="space-y-2"
    >
      <div
        className={cn(
          "flex items-end gap-2 rounded-xl border bg-surface-raised p-2",
          "focus-within:ring-2 focus-within:ring-accent/40",
          tooLong ? "border-refused" : "border-line-strong",
        )}
      >
        <Search className="mb-2 ml-1.5 size-4 shrink-0 text-ink-muted" aria-hidden="true" />

        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            // Enter submits, Shift+Enter newlines — the convention every chat UI uses, and
            // violating it is a papercut on every single message.
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          autoFocus={autoFocus}
          placeholder="Ask about a condition, symptom, or treatment…"
          aria-label="Your question"
          aria-invalid={tooLong}
          aria-describedby="question-hint"
          className="max-h-40 min-h-9 flex-1 resize-none bg-transparent py-2 text-base text-ink outline-none placeholder:text-ink-muted"
        />

        {busy ? (
          <Button type="button" variant="outline" onClick={onCancel} aria-label="Stop generating">
            <Square className="size-3.5" aria-hidden="true" />
            Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!canSubmit} aria-label="Ask">
            Ask
            <CornerDownLeft className="size-3.5" aria-hidden="true" />
          </Button>
        )}
      </div>

      <p id="question-hint" className="px-1 text-xs text-ink-muted">
        {tooLong ? (
          <span className="text-refused">
            {Math.abs(remaining)} characters over the {MAX_LENGTH} limit.
          </span>
        ) : (
          <>Press Enter to ask, Shift + Enter for a new line.</>
        )}
      </p>
    </form>
  );
}
