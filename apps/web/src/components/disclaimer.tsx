import { Info } from "lucide-react";

/**
 * NON-DISMISSIBLE by requirement — there is deliberately no close control, and it lives in
 * the root layout so no route can render without it.
 *
 * `role` is intentionally omitted: an alert role would re-announce on every navigation and
 * become noise a screen-reader user learns to skip past — which is exactly how a safety
 * notice stops being a safety notice. It is a landmark-free static region, read in order.
 */
export function Disclaimer() {
  return (
    <div className="border-b border-line bg-surface-raised">
      <p className="mx-auto flex max-w-5xl items-start gap-2 px-4 py-2.5 text-sm text-ink-muted">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>
          <span className="font-medium text-ink">General information, not medical advice.</span>{" "}
          This assistant answers only from a medical reference corpus. It cannot diagnose,
          prescribe, or replace a clinician. In an emergency, contact your local emergency
          services.
        </span>
      </p>
    </div>
  );
}
