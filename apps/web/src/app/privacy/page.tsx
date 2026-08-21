import { PageShell, Section } from "@/components/page-shell";

export const metadata = {
  title: "Privacy — Medical Reference Assistant",
  description: "What is stored when you ask a health question here, and how to delete it.",
};

export default function Privacy() {
  return (
    <PageShell
      title="Privacy"
      intro="Health questions are sensitive by nature. This page describes exactly what is kept, for how long, and how to remove it."
    >
      <Section heading="No account, no profile">
        <p>
          There is no sign-up and no user profile. Your browser is given an anonymous session
          identifier in a cookie so that a conversation holds together across a few
          questions. It contains a random identifier and nothing else — no name, no email, no
          identity. It cannot be read by JavaScript.
        </p>
      </Section>

      <Section heading="What is stored">
        <p>
          The questions you ask and the answers you receive are stored against that anonymous
          session so the conversation can be shown back to you. They are deleted
          automatically after <span className="font-medium text-ink">30 days</span>.
        </p>
        <p>
          You can delete them immediately using{" "}
          <span className="font-medium text-ink">Delete my data</span> on the main page. It
          reports how many stored messages were actually removed, rather than simply claiming
          success.
        </p>
      </Section>

      <Section heading="What is not stored">
        <p>
          Question text is never written to the application logs. Operational logs record a
          one-way fingerprint of a question — enough to notice the same question being asked
          repeatedly, never enough to reconstruct what was asked.
        </p>
        <p>There is no third-party analytics, advertising, or tracking on this site.</p>
      </Section>

      <Section heading="Where your question goes">
        <p>
          Answering a question requires sending it, together with the retrieved reference
          passages, to a language model. Depending on configuration that model may be hosted
          by a third-party provider, in which case your question text reaches that provider
          in order to be answered. No session identifier or other information about you is
          sent with it.
        </p>
      </Section>

      <Section heading="Limits and abuse prevention">
        <p>
          The number of questions from one session and one network address is limited, to
          keep the service available and its costs bounded. Enforcing that requires keeping a
          short-lived, one-way hash of the network address. It is not stored alongside your
          questions as an identifier of you.
        </p>
      </Section>

      <Section heading="This is a portfolio project">
        <p>
          This service is built to demonstrate production engineering practice. It is not
          operated as a commercial medical service, it has not been through a formal
          compliance audit, and it should not be used as though it had been. Do not enter
          information you would not be comfortable having stored for 30 days.
        </p>
      </Section>
    </PageShell>
  );
}
