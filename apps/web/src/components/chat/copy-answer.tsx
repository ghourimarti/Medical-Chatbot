"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Answer } from "@/lib/contract";

/**
 * Copy an answer WITH its sources (F4.5).
 *
 * Copying the prose alone would strip exactly what makes this product different. A medical
 * paragraph pasted into a note, an email or a message to a relative, with its "[1]" markers
 * intact but no key for them, is less trustworthy than the original and looks like it came
 * from nowhere. So the citations travel with it.
 *
 * Refusals and no-answers are copyable too — someone forwarding "this assistant would not
 * give me a dose, go and ask a pharmacist" is a GOOD outcome, and silently disabling the
 * button there would be a strange thing to explain.
 */
export function CopyAnswer({ answer }: { answer: Answer }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clearing on unmount: without it, switching threads while the "Copied" tick is showing
  // fires setState on a component that is gone.
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = useCallback(async () => {
    const sources = answer.citations
      .map((c, i) => `[${i + 1}] ${c.source}${c.page !== null ? `, p.${c.page}` : ""}`)
      .join("\n");
    const payload = sources ? `${answer.text}\n\nSources\n${sources}` : answer.text;

    try {
      // navigator.clipboard is undefined on a non-secure origin and can REJECT even on
      // one, if the document is not focused. Both are ordinary, so the button reports
      // failure rather than pretending it worked.
      await navigator.clipboard.writeText(payload);
      setState("copied");
    } catch {
      setState("failed");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  }, [answer]);

  return (
    <Button variant="ghost" size="sm" onClick={() => void copy()}>
      {state === "copied" ? (
        <Check className="size-3.5" aria-hidden="true" />
      ) : (
        <Copy className="size-3.5" aria-hidden="true" />
      )}
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}
      {/* The icon swap alone is invisible to a screen reader, and the label change is not
          announced because the button is not a live region. */}
      <span className="sr-only" role="status" aria-live="polite">
        {state === "copied"
          ? "Answer and sources copied to the clipboard"
          : state === "failed"
            ? "Could not copy to the clipboard"
            : ""}
      </span>
    </Button>
  );
}
