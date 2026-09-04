"use client";

import { useState } from "react";
import { CornerDownLeft, Square } from "lucide-react";
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
    // Clear on send, like every other chat input.
    //
    // Without this the question stayed in the box after the answer arrived, so asking a
    // second question meant selecting or backspacing the first one out. Worse, the box
    // then looked pre-filled with something already answered, which reads as "your
    // question was not sent".
    //
    // `onSubmit` is fire-and-forget (the surface owns the request), so there is nothing to
    // await and nothing to roll back — the question is preserved in the transcript the
    // moment it is sent, which is where a user would look for it anyway.
    setValue("");
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="space-y-2"
    >
      {/* A pill, not a bordered box. The shape is doing real work: a rectangle with a
          hairline border reads as a FORM FIELD — something you fill in and submit — while
          a soft, raised pill reads as somewhere you talk. Every product in this category
          converged on it for that reason, not for decoration. */}
      <div
        className={cn(
          "flex items-end gap-2 rounded-[1.75rem] border bg-surface-raised px-4 py-2.5",
          "shadow-[var(--shadow-sm)] transition-shadow duration-200",
          "focus-within:shadow-[var(--shadow-md)] focus-within:ring-2 focus-within:ring-accent/30",
          tooLong ? "border-refused" : "border-line",
        )}
      >

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
          placeholder="Ask about a condition, symptom, or treatment"
          aria-label="Your question"
          aria-invalid={tooLong}
          aria-describedby="question-hint"
          className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-1 py-2.5 text-base text-ink outline-none placeholder:text-ink-muted"
        />

        {busy ? (
          <Button type="button" variant="outline" onClick={onCancel} aria-label="Stop generating" className="rounded-full">
            <Square className="size-3.5" aria-hidden="true" />
            Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!canSubmit} aria-label="Ask" className="rounded-full">
            Ask
            <CornerDownLeft className="size-3.5" aria-hidden="true" />
          </Button>
        )}
      </div>

      <p id="question-hint" className="px-4 text-xs text-ink-muted">
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
