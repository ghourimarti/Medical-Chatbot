import { PageShell, Section } from "@/components/page-shell";

export const metadata = {
  title: "Safety and limitations — Medical Reference Assistant",
  description: "What this assistant will not do, and why.",
};

const REFUSALS: { what: string; why: string }[] = [
  {
    what: "Diagnose your symptoms",
    why: "A diagnosis needs an examination and a history. Guessing from a description is how a serious condition gets mistaken for a minor one.",
  },
  {
    what: "Give you a drug dose",
    why: "Doses depend on age, weight, kidney and liver function, and other medications. Getting one wrong is dangerous, and this assistant knows none of those things about you.",
  },
  {
    what: "Tell you to start, stop, or change a medication",
    why: "Stopping some medicines abruptly causes harm. That decision belongs to the clinician who prescribed it.",
  },
  {
    what: "Recommend or help you obtain a prescription medicine",
    why: "A prescriber has to assess you first.",
  },
  {
    what: "Assess an urgent situation",
    why: "If something may be an emergency, the only safe answer is to contact emergency services now. Waiting for information could cost time that matters.",
  },
];

export default function Safety() {
  return (
    <PageShell
      title="Safety and limitations"
      intro="This assistant refuses some questions on purpose. Those refusals are the feature, not a gap in it."
    >
      <div className="rounded-lg border-2 border-emergency bg-emergency-wash p-5">
        <h2 className="text-lg font-semibold text-emergency">If this is an emergency</h2>
        <p className="mt-2 text-ink">
          Contact your local emergency services immediately, or go to the nearest emergency
          department. Do not wait for information from this or any other website.
        </p>
      </div>

      <Section heading="What it will not do">
        <ul className="space-y-3">
          {REFUSALS.map((r) => (
            <li key={r.what}>
              <span className="font-medium text-ink">{r.what}.</span>{" "}
              <span className="text-ink-muted">{r.why}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section heading="What it can get wrong">
        <p>
          The reference corpus is a general medical encyclopedia. It is not exhaustive, it is
          not current with the latest research, and it will not contain many topics you might
          ask about. When a topic is missing, the assistant says so — but an answer being
          well-sourced does not make it complete, current, or right for you.
        </p>
        <p>
          Answers are written by a language model. Even constrained to retrieved passages, a
          model can summarise them poorly or emphasise the wrong part. That is why every
          sourced answer shows its passages: so you can read the original rather than
          trusting the summary.
        </p>
      </Section>

      <Section heading="Why refusals look the way they do">
        <p>
          A refusal here is not an error message and is not a scold. It explains why the
          question needs a person, and points you at one. Urgent situations get a
          deliberately different, unmissable treatment — the only place this interface uses
          red, so that when you see it, it means something.
        </p>
      </Section>
    </PageShell>
  );
}
