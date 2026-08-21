"use client";

import { CloudOff, Hourglass, RotateCw, ServerCrash, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ProblemDetail } from "@/lib/contract";

/**
 * Designed failure states (S10.9).
 *
 * Each cause gets its own copy, because "what should I do now?" differs for every one of
 * them: a quota is a wait, a provider outage is a retry, a degraded service is a partial
 * capability. A single generic error box gives the user no way to tell those apart and
 * teaches them that the product is simply unreliable.
 *
 * NONE of these use red. Red is reserved exclusively for medical emergencies (D27) — a
 * failed request is an inconvenience, and dressing it in the same colour as chest pain is
 * how the emergency signal stops working.
 *
 * The copy is OURS, not the server's `detail`. The API writes for an operator; these are
 * written for a worried person at 2 a.m., and they say what happens next.
 */
interface Presentation {
  title: string;
  body: string;
  icon: LucideIcon;
  retryable: boolean;
}

function present(problem: ProblemDetail): Presentation {
  const slug = problem.type.split("/").pop() ?? "";

  if (problem.status === 429 || slug === "quota-exceeded") {
    return {
      title: "You have reached the request limit",
      body:
        "This service limits how many questions each visitor can ask, so it stays available " +
        "for everyone. Please wait a minute and try again.",
      icon: Hourglass,
      // Retrying immediately would just fail again and look broken.
      retryable: false,
    };
  }

  if (slug === "service-degraded" || slug === "upstream-unavailable") {
    return {
      title: "Answers are limited right now",
      body:
        "The assistant is running in a reduced mode and cannot generate a new answer. " +
        "This is a problem on our side, not with your question.",
      icon: CloudOff,
      retryable: true,
    };
  }

  if (slug === "retrieval-unavailable") {
    return {
      title: "The reference library is unavailable",
      body:
        "The assistant cannot reach its medical reference material, and it will not answer " +
        "from memory. Please try again shortly.",
      icon: WifiOff,
      retryable: true,
    };
  }

  if (slug === "provider-error" || problem.status === 502) {
    return {
      title: "The answering model is temporarily unavailable",
      body: "This usually clears within a few moments. Your question was not lost.",
      icon: ServerCrash,
      retryable: true,
    };
  }

  return {
    title: "Something went wrong",
    body: "The request did not complete. Please try again.",
    icon: ServerCrash,
    retryable: true,
  };
}

export function ErrorState({
  problem,
  onRetry,
}: {
  problem: ProblemDetail;
  onRetry: () => void;
}) {
  const { title, body, icon: Icon, retryable } = present(problem);

  return (
    <div
      data-error-slug={problem.type.split("/").pop() ?? "unknown"}
      className="rounded-lg border border-line bg-surface-raised p-5"
    >
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-5 shrink-0 text-degraded" aria-hidden="true" />
        <div className="min-w-0 space-y-2">
          <h2 className="text-sm font-medium text-ink">{title}</h2>
          <p className="max-w-[68ch] text-sm text-ink-muted">{body}</p>
          {retryable && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              <RotateCw className="size-3.5" aria-hidden="true" />
              Try again
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Persistent banner while the service is degraded, driven by GET /api/v1/status.
 *
 * Separate from ErrorState because it is a STANDING condition rather than a failed
 * request: answers may still be served from cache, so the honest message is "limited",
 * not "broken".
 */
export function DegradedBanner() {
  return (
    <div className="rounded-md border border-degraded/30 bg-degraded-wash px-4 py-2.5">
      <p className="flex items-center gap-2 text-sm text-ink">
        <CloudOff className="size-4 shrink-0 text-degraded" aria-hidden="true" />
        <span>
          <span className="font-medium">Limited service.</span> New answers are not being
          generated right now. Previously answered questions may still work.
        </span>
      </p>
    </div>
  );
}
