import type { Metadata } from "next";
import { PageShell, Section } from "@/components/page-shell";

export const metadata: Metadata = {
  title: "About — Medical Reference Assistant",
  description:
    "What this assistant is, who built it, what corpus it reads, and what it deliberately will not do.",
};

/**
 * About (F8).
 *
 * A server component with no client JS, like the other public pages.
 *
 * The temptation with an "about" page in a medical product is to write reassurance. This
 * one writes LIMITS instead, because reassurance is exactly what a reader cannot verify
 * and limits are what they can hold the product to. Everything stated here is checkable
 * against behaviour: the corpus is named, the refusals are enumerable, and the "no
 * training on your questions" claim is a consequence of the architecture rather than a
 * promise — there is no training pipeline to feed.
 */
export default function AboutPage() {
  return (
    <PageShell
      title="About this assistant"
      intro="A medical reference assistant that answers only from a fixed encyclopedia, cites every claim, and says so when the answer is not there."
    >
      <Section heading="What it is">
        <p>
          A retrieval-augmented question answering system over the{" "}
          <strong>Gale Encyclopedia of Medicine (2nd edition)</strong>. A question is
          embedded, matched against roughly 7,000 passages of that encyclopedia, reranked,
          and answered <em>only</em> from the passages that come back. The sources are shown
          with every answer so you can check the claim rather than trust it.
        </p>
      </Section>

      <Section heading="What it is not">
        <p>
          It is not a clinician, a triage service, or a second opinion. It cannot examine
          you, does not know your history, and has no access to anything beyond that one
          encyclopedia. It will not tell you what condition you have, and it will not tell
          you how much of a medicine to take — those two refusals are deliberate and
          enforced in the system rather than left to the model&apos;s judgement.
        </p>
      </Section>

      <Section heading="Where the answers come from">
        <p>
          One corpus, named and fixed. If your question is not covered by it, the honest
          response is &ldquo;I don&apos;t have reliable information on that&rdquo; — and
          that is what you get, rather than a plausible paragraph assembled from nothing.
          An answer with no citation is a bug here, not a style choice.
        </p>
      </Section>

      <Section heading="What happens to your questions">
        <p>
          Questions are kept so your conversation has a history, and removed after 30 days.
          You can delete everything at any time from Settings, and the app tells you how
          many records it removed rather than simply claiming success. Your questions are
          not used to train anything — there is no training pipeline in this system to feed
          them to.
        </p>
      </Section>

      <Section heading="Why it was built">
        <p>
          As a demonstration that a medical answering system can be held to verifiable
          standards: every claim cited, every refusal categorised, every answer traceable to
          the passages that produced it. Most of the engineering here is not the answering —
          it is the machinery that makes the answering checkable.
        </p>
      </Section>
    </PageShell>
  );
}
