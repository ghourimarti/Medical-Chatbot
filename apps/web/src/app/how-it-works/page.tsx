import { PageShell, Section } from "@/components/page-shell";

export const metadata = {
  title: "How it works — Medical Reference Assistant",
  description: "How answers are retrieved, cited, and when the assistant declines to answer.",
};

export default function HowItWorks() {
  return (
    <PageShell
      title="How it works"
      intro="This assistant does not answer from memory. It searches a medical reference corpus, shows you the passages it found, and writes an answer from those passages only."
    >
      <Section heading="1. Your question is checked first">
        <p>
          Before anything is searched, the question is checked against a safety policy. If it
          asks for a personal diagnosis, a drug dose, or describes a possible emergency, the
          assistant declines and points you to a clinician or to emergency services. Nothing
          is retrieved and no answer is generated for those questions.
        </p>
      </Section>

      <Section heading="2. The reference corpus is searched">
        <p>
          The question is converted into a numerical representation and matched against the
          corpus two ways at once: by meaning, and by keyword. The two result sets are
          combined, then re-ranked by a second model that reads each candidate passage
          against your question and scores how well it actually answers it.
        </p>
        <p>
          Only the highest-scoring passages are kept, and only those are shown to the model
          that writes the answer.
        </p>
      </Section>

      <Section heading="3. The answer is written from those passages">
        <p>
          The model is instructed to use the retrieved passages and nothing else, and to cite
          the passage number for each claim. Text retrieved from the corpus is treated as
          reference data, never as instructions — so a passage cannot change how the
          assistant behaves.
        </p>
        <p>
          Every sourced answer shows its passages. You can open any of them to read the text
          the answer was built from, and check it yourself.
        </p>
      </Section>

      <Section heading="4. When it does not know, it says so">
        <p>
          If nothing retrieved clears a relevance threshold, the assistant tells you the
          topic is not in its reference material rather than guessing. This is the single
          most important behaviour in the system: a confident answer drawn from a model’s
          memory rather than the corpus is indistinguishable from a correct one until it
          matters.
        </p>
        <p>
          If a citation marker in an answer refers to a passage that does not exist, it is
          shown as plain text rather than as a link — the assistant will not present a
          source it cannot show you.
        </p>
      </Section>

      <Section heading="What this is not">
        <p>
          It is not a diagnostic tool, a triage service, or a substitute for a clinician. It
          cannot see your history, your test results, or you. It answers questions about
          conditions in general, not about your condition in particular.
        </p>
      </Section>
    </PageShell>
  );
}
