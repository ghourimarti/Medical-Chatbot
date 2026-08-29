import { AnswerCard } from "@/components/answer/answer-card";
import { TREATMENTS, resolveTreatment } from "@/components/answer/kind-meta";
import { Button } from "@/components/ui/button";
import type { Answer, AnswerKind, Citation, RefusalCategory } from "@/lib/contract";

/**
 * Design gallery (S10.4).
 *
 * Exists so the system can be REVIEWED and screenshotted rather than described, and so a
 * regression in one treatment is visible beside the others. Every string is the copy the
 * backend actually returns — verbatim from medapi.guardrails._MESSAGES and a live grounded
 * answer — because a gallery of lorem ipsum proves the CSS works and nothing about whether
 * the real content fits.
 */
export const metadata = { title: "Design system — Medical Reference Assistant" };

function answer(
  kind: AnswerKind,
  text: string,
  opts: { citations?: Citation[]; category?: RefusalCategory } = {},
): Answer {
  return {
    kind,
    text,
    citations: opts.citations ?? [],
    confidence: null,
    model_id: "openai/gpt-oss-20b",
    usage: { prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 },
    timings: {
      condense_ms: null,
      embed_ms: 441,
      retrieve_ms: 22,
      rerank_ms: 1359,
      generate_ms: 820,
      ttft_ms: 1579,
      total_ms: 2642,
    },
    cache_hit: false,
    refusal_category: opts.category ?? null,
  };
}

const SOURCE = "Gale Encyclopedia of Medicine (2nd ed.)";
const CITATIONS: Citation[] = [
  { chunk_id: "a1", source: SOURCE, page: 30, snippet: "", score: 0.726 },
  { chunk_id: "a2", source: SOURCE, page: 30, snippet: "", score: 0.714 },
  { chunk_id: "a3", source: SOURCE, page: 29, snippet: "", score: 0.293 },
];

const SAMPLES: { heading: string; note: string; answer: Answer }[] = [
  {
    heading: "grounded",
    note: "Sourced answer. Serif body, citations visible, teal. Confident, not boastful.",
    answer: answer(
      "grounded",
      "Chronic pain is managed with medications taken consistently and regularly rather than on an as-needed basis. The World Health Organization analgesic ladder is used to select an appropriate drug for the level of pain reported [1].",
      { citations: CITATIONS },
    ),
  },
  {
    heading: "grounded / out-of-range citation guard",
    note: "The model emitted [9] when only 3 passages were retrieved. An out-of-range marker renders as PLAIN TEXT, never as a link. Manufacturing provenance the system does not have is the exact failure this whole design exists to prevent.",
    answer: answer(
      "grounded",
      "Pain is assessed using a numeric rating scale [1]. Some clinicians also use a visual analogue scale [9].",
      { citations: CITATIONS },
    ),
  },
  {
    heading: "no_answer",
    note: "Honest abstention. SLATE, never a warning colour — rendering candour as a malfunction teaches users to distrust the abstentions that protect them.",
    answer: answer(
      "no_answer",
      "I don't have reliable information on that in my reference material.",
    ),
  },
  {
    heading: "refused · dosage",
    note: "Care, not a scold. Amber, stethoscope, clinician redirect.",
    answer: answer(
      "refused",
      "I can't provide dosage information. Doses depend on age, weight, kidney and liver function, and other medications — getting them wrong is dangerous. Please ask your pharmacist or prescribing clinician, or check the patient information leaflet.",
      { category: "dosage" },
    ),
  },
  {
    heading: "refused · diagnosis",
    note: "Same treatment as dosage: a routine refusal that offers what it CAN do instead.",
    answer: answer(
      "refused",
      "I can't diagnose individual symptoms — that requires an examination and history that I don't have. Please speak with a qualified healthcare provider. I'm happy to share general information about a condition instead.",
      { category: "diagnosis" },
    ),
  },
  {
    heading: "refused · emergency  →  EMERGENCY treatment",
    note: "The only red in the system. Structurally different: role=alert, action before explanation, and no invented phone number.",
    answer: answer(
      "refused",
      "This may be a medical emergency. Please contact your local emergency services immediately, or go to the nearest emergency department. I can't assess urgent symptoms, and waiting for information could be dangerous.",
      { category: "emergency" },
    ),
  },
  {
    heading: "refused · harmful  →  EMERGENCY treatment",
    note: "Caught in review: this category carries crisis-helpline copy, so it must escalate. It was missing from the frontend type entirely until the contract guard was written.",
    answer: answer(
      "refused",
      "I can't help with that. If you're in distress, please contact your local emergency services or a crisis helpline — support is available right now.",
      { category: "harmful" },
    ),
  },
  {
    heading: "degraded",
    note: "System-level voice. Stone, no blame — this is us, not you.",
    answer: answer(
      "degraded",
      "Answers are limited right now and I can't generate a new one. Please try again shortly.",
    ),
  },
];

const MAP: [AnswerKind, RefusalCategory | null][] = [
  ["grounded", null],
  ["no_answer", null],
  ["refused", "dosage"],
  ["refused", "diagnosis"],
  ["refused", "prescription"],
  ["refused", "medication_change"],
  ["refused", "injection"],
  ["refused", "emergency"],
  ["refused", "self_harm"],
  ["refused", "harmful"],
  ["degraded", null],
];

export default function DesignPage() {
  return (
    <div className="space-y-10">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold">Design system</h1>
        <p className="max-w-[68ch] text-ink-muted">
          Every answer kind, rendered with the copy the backend actually returns. Use the
          header controls to check both densities (D27b) and both themes. All 30 colour
          pairs are verified against WCAG AA by scripts/check-contrast.mjs.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Treatment map</h2>
        {/* tabIndex + role + label, not just `overflow-x-auto` (axe: scrollable-region-
            focusable). The table is min-w-[36rem], so on a phone it scrolls sideways
            INSIDE this box — and a container that only responds to a swipe or a trackpad
            is unreachable for anyone driving the page from the keyboard, who has no way
            to bring the right-hand columns into view at all.
            Pre-existing and invisible to CI because the a11y suite is only ever run under
            `--project=chromium`, where the viewport is wide enough that nothing scrolls. */}
        <div
          className="overflow-x-auto"
          tabIndex={0}
          role="region"
          aria-label="Treatment map (scrolls horizontally)"
        >
          <table className="w-full min-w-[36rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-ink-muted">
                <th className="py-2 pr-4 font-medium">kind / category</th>
                <th className="py-2 pr-4 font-medium">treatment</th>
                <th className="py-2 font-medium">label</th>
              </tr>
            </thead>
            <tbody>
              {MAP.map(([kind, category]) => {
                const t = resolveTreatment(kind, category);
                const meta = TREATMENTS[t];
                const Icon = meta.icon;
                return (
                  <tr key={kind + String(category)} className="border-b border-line/60">
                    <td className="py-2 pr-4 font-mono text-xs">
                      {kind}
                      {category ? " / " + category : ""}
                    </td>
                    <td className={"py-2 pr-4 " + meta.fg}>
                      <span className="inline-flex items-center gap-1.5">
                        <Icon className="size-3.5" aria-hidden="true" />
                        {t}
                      </span>
                    </td>
                    <td className="py-2 text-ink-muted">{meta.label}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-8">
        <h2 className="text-xl font-semibold">Answer treatments</h2>
        {SAMPLES.map((s) => (
          <div key={s.heading} className="space-y-2">
            <h3 className="font-mono text-sm text-ink-muted">{s.heading}</h3>
            <p className="max-w-[68ch] text-sm text-ink-muted">{s.note}</p>
            <AnswerCard answer={s.answer} />
          </div>
        ))}
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Controls</h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button>Ask</Button>
          <Button variant="outline">Stop</Button>
          <Button variant="ghost">Clear</Button>
          <Button variant="emergency">Emergency action</Button>
        </div>
        <p className="max-w-[68ch] text-sm text-ink-muted">
          There is deliberately no red destructive variant. Red is reserved for medical
          emergencies; spending it on a delete confirmation is how the one signal that must
          mean act now stops meaning anything.
        </p>
      </section>
    </div>
  );
}
