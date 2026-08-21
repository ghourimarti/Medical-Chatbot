import { LifeBuoy, Phone, TriangleAlert } from "lucide-react";
import type { Answer, RefusalCategory } from "@/lib/contract";

/**
 * The urgent treatment — structurally different, not merely a red variant.
 *
 * Design decisions, each deliberate:
 *  - role="alert": announced immediately by assistive tech. Justified HERE and almost
 *    nowhere else; using it on routine content trains users to tune it out.
 *  - Action BEFORE explanation: someone with chest pain should not have to read a
 *    paragraph to find out what to do.
 *  - NO tel: link and NO phone number. Emergency numbers differ by country, and a wrong
 *    number during an emergency is a catastrophic failure. "Your local emergency services"
 *    is honest; hardcoding 911 would be a guess about where the user lives.
 *
 * CAUGHT IN REVIEW: this component originally hardcoded "This may be a medical emergency"
 * for every urgent category — so a self-harm or distress disclosure was met with
 * clinical-alarm framing. Urgency is right for both; the VOICE is not the same. A person
 * in distress needs "support is available", not "go to the emergency department".
 */
const URGENT_COPY: Record<
  "medical" | "crisis",
  { heading: string; action: string; Icon: typeof TriangleAlert }
> = {
  medical: {
    heading: "This may be a medical emergency",
    action:
      "Contact your local emergency services now, or go to the nearest emergency department.",
    Icon: TriangleAlert,
  },
  crisis: {
    heading: "Support is available right now",
    action:
      "Please contact your local emergency services or a crisis helpline now — someone is available to talk to you.",
    Icon: LifeBuoy,
  },
};

function voiceFor(category: RefusalCategory | null): "medical" | "crisis" {
  return category === "self_harm" || category === "harmful" ? "crisis" : "medical";
}

export function EmergencyCard({ answer }: { answer: Answer }) {
  const { heading, action, Icon } = URGENT_COPY[voiceFor(answer.refusal_category)];

  return (
    <article
      data-answer-kind="emergency"
      role="alert"
      className="rounded-lg border-2 border-emergency bg-emergency-wash p-6"
      aria-labelledby="urgent-heading"
    >
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-6 shrink-0 text-emergency" aria-hidden="true" />
        <div className="min-w-0">
          <h2 id="urgent-heading" className="text-xl font-semibold text-emergency">
            {heading}
          </h2>

          <p className="mt-3 flex items-start gap-2 text-base font-medium text-ink">
            <Phone className="mt-1 size-4 shrink-0 text-emergency" aria-hidden="true" />
            {action}
          </p>

          <p className="mt-4 max-w-[68ch] text-base leading-relaxed text-ink">{answer.text}</p>
        </div>
      </div>
    </article>
  );
}
