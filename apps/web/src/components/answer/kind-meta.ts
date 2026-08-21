import {
  BookOpenCheck,
  CloudOff,
  CircleHelp,
  Stethoscope,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { AnswerKind, RefusalCategory } from "@/lib/contract";

/**
 * SINGLE SOURCE OF TRUTH for how an answer is presented.
 *
 * `kind` alone is not enough: a refusal for a *dosage* question and a refusal for
 * "crushing chest pain" are the same kind but must not look the same. Resolving that here
 * — once — means no individual renderer gets to make a safety-presentation decision, which
 * is the same reasoning that put refusal_category in the API instead of leaving clients to
 * pattern-match prose (S10.2a).
 */
export type Treatment = "grounded" | "no_answer" | "refused" | "emergency" | "degraded";

// Which refusals are URGENT rather than routine. Derived from the backend's actual copy,
// not guessed: `harmful` reads "If you're in distress, please contact your local emergency
// services or a crisis helpline", which is crisis-flavoured and must not render as a calm
// amber "ask your pharmacist" card.
//
// CAUGHT IN REVIEW: this file originally typed only 5 of the backend's 8 categories.
// prescription / medication_change / harmful were missing, so `harmful` — the one carrying
// a crisis helpline — would have fallen through to the routine treatment.
const URGENT: ReadonlySet<RefusalCategory> = new Set([
  "emergency",
  "self_harm",
  "harmful",
]);

export function resolveTreatment(
  kind: AnswerKind,
  category: RefusalCategory | null,
): Treatment {
  if (kind === "refused") return category && URGENT.has(category) ? "emergency" : "refused";
  return kind;
}

export interface TreatmentMeta {
  /** Visible text label. Colour NEVER carries meaning alone (WCAG 1.4.1): this survives
   *  greyscale, colour-blindness and a screen reader. */
  label: string;
  icon: LucideIcon;
  /** Tailwind tokens; `wash` is the tinted background, `fg` the text/icon colour. */
  fg: string;
  wash: string;
  border: string;
}

export const TREATMENTS: Record<Treatment, TreatmentMeta> = {
  grounded: {
    label: "Answer from the reference corpus",
    icon: BookOpenCheck,
    fg: "text-grounded",
    wash: "bg-grounded-wash",
    border: "border-grounded/30",
  },
  no_answer: {
    // Deliberately SLATE, never a warning colour. Rendering an honest abstention in amber
    // teaches users that candour is a malfunction — and they then distrust the very
    // abstentions that protect them from a confabulated medical answer.
    label: "Not in the reference material",
    icon: CircleHelp,
    fg: "text-no-answer",
    wash: "bg-no-answer-wash",
    border: "border-no-answer/25",
  },
  refused: {
    // Supportive, not a stop sign: a refusal should read as care and point at a clinician.
    label: "This needs a clinician",
    icon: Stethoscope,
    fg: "text-refused",
    wash: "bg-refused-wash",
    border: "border-refused/30",
  },
  emergency: {
    // The ONLY red in the system.
    label: "Seek emergency care now",
    icon: TriangleAlert,
    fg: "text-emergency",
    wash: "bg-emergency-wash",
    border: "border-emergency/50",
  },
  degraded: {
    label: "Limited service",
    icon: CloudOff,
    fg: "text-degraded",
    wash: "bg-degraded-wash",
    border: "border-degraded/25",
  },
};
