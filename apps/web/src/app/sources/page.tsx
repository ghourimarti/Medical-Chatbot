import { PageShell, Section } from "@/components/page-shell";

export const metadata = {
  title: "Sources — Medical Reference Assistant",
  description: "What this assistant knows, and what it does not.",
};

/** Verified against the corpus itself during evaluation, not estimated. */
const ABSENT = [
  "COVID-19 and SARS-CoV-2",
  "CRISPR and gene editing",
  "Zika virus",
  "mpox",
  "GLP-1 medicines such as semaglutide",
  "mRNA vaccines",
  "Vaping and e-cigarettes",
  "West Nile virus",
];

export default function Sources() {
  return (
    <PageShell
      title="Sources"
      intro="Every answer comes from one reference work. Knowing exactly what that is tells you what the assistant can and cannot answer."
    >
      <Section heading="The corpus">
        <p>
          <span className="font-medium text-ink">The Gale Encyclopedia of Medicine,
          second edition</span> — a general medical reference covering conditions, symptoms,
          treatments and procedures, written for a non-specialist reader.
        </p>
        <p>
          The text is split into passages and indexed for search. Every citation shown with
          an answer points to a specific passage and page in that work.
        </p>
      </Section>

      <Section heading="What it does not cover">
        <p>
          The edition indexed here predates a great deal of modern medicine. The following
          were checked directly against the corpus and are <span className="font-medium">not
          present at all</span>:
        </p>
        <ul className="ml-5 list-disc space-y-1 text-ink-muted">
          {ABSENT.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <p>
          Asked about any of these, the assistant will tell you the topic is not in its
          reference material. That is the correct answer, and a more useful one than a
          confident summary assembled from a model’s memory.
        </p>
      </Section>

      <Section heading="Coverage is uneven">
        <p>
          Because the corpus is a single alphabetical work, coverage depends on which
          article a topic falls under, and how much of that article survives text
          extraction. Some questions that sound similar will get very different results.
        </p>
      </Section>

      <Section heading="Why only one source">
        <p>
          A single, named, checkable corpus is what makes the citations meaningful. You can
          look up the page. Adding more sources without the same traceability would make the
          assistant appear to know more while making any individual claim harder to verify.
        </p>
      </Section>
    </PageShell>
  );
}
