"use client";

import { useState } from "react";
import { Check, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Delete my data (S10.8) — the GDPR right-to-erasure control (D18).
 *
 * Two decisions worth naming:
 *
 * 1. NO RED BUTTON, even though this is destructive. Red is reserved exclusively for
 *    medical emergencies (D27). A red Delete here would spend the one signal that has to
 *    mean "act now" on a routine confirmation, and the next real emergency would land in a
 *    UI where the user has already learned that red means "are you sure?".
 *
 * 2. It reports the NUMBER OF ROWS REMOVED, because the API does. A delete control that
 *    says "Done" without evidence passes review and fails an audit — and the person most
 *    likely to use this is someone who wants proof their health questions are gone.
 */
export function DeleteMyData({ onDeleted }: { onDeleted: () => void }) {
  const [state, setState] = useState<"idle" | "confirming" | "working" | "done" | "error">(
    "idle",
  );
  const [deleted, setDeleted] = useState(0);

  async function confirm() {
    setState("working");
    try {
      const res = await fetch("/api/v1/session/clear", { method: "POST" });
      if (!res.ok) {
        setState("error");
        return;
      }
      const body = (await res.json()) as { deleted: number };
      setDeleted(body.deleted);
      setState("done");
      onDeleted();
    } catch {
      setState("error");
    }
  }

  if (state === "done") {
    return (
      <p className="flex items-center gap-2 text-sm text-ink-muted">
        <Check className="size-4 text-grounded" aria-hidden="true" />
        Deleted {deleted} stored message{deleted === 1 ? "" : "s"}. Nothing from this
        session remains on the server.
      </p>
    );
  }

  if (state === "confirming" || state === "working") {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink">
          Delete every question and answer stored for this session?
        </span>
        <Button variant="outline" size="sm" onClick={confirm} disabled={state === "working"}>
          {state === "working" ? "Deleting…" : "Yes, delete"}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setState("idle")}>
          Cancel
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <Button variant="ghost" size="sm" onClick={() => setState("confirming")}>
        <Trash2 className="size-3.5" aria-hidden="true" />
        Delete my data
      </Button>
      {state === "error" && (
        <p className="text-sm text-refused">
          The deletion did not complete. Nothing was removed — please try again.
        </p>
      )}
    </div>
  );
}
