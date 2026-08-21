import Link from "next/link";
import { PageShell, Section } from "@/components/page-shell";

export const metadata = {
  title: "Terms — Medical Reference Assistant",
  description: "The terms on which this assistant is provided.",
};

export default function Terms() {
  return (
    <PageShell
      title="Terms"
      intro="Plain terms for a demonstration service. If any of this is unacceptable to you, please do not use it."
    >
      <Section heading="Not medical advice">
        <p>
          This service provides general information from a medical reference work for
          educational purposes. It is not medical advice, it does not create a
          clinician-patient relationship, and it must not be used to diagnose or treat
          anyone. Always consult a qualified healthcare professional about your own health,
          and never delay seeking care because of something you read here.
        </p>
        <p>
          In an emergency, contact your local emergency services immediately.
        </p>
      </Section>

      <Section heading="No warranty">
        <p>
          The service is provided as-is, without warranty of any kind. Answers may be
          incomplete, out of date, or wrong. See{" "}
          <Link href="/safety" className="text-accent underline underline-offset-2">
            Safety and limitations
          </Link>{" "}
          and{" "}
          <Link href="/sources" className="text-accent underline underline-offset-2">
            Sources
          </Link>{" "}
          for the specific ways that happens.
        </p>
      </Section>

      <Section heading="Availability">
        <p>
          This is a demonstration project with no uptime commitment. It may be unavailable,
          rate-limited, or withdrawn at any time. Current health is shown on the{" "}
          <Link href="/status" className="text-accent underline underline-offset-2">
            status page
          </Link>
          .
        </p>
      </Section>

      <Section heading="Acceptable use">
        <p>
          Do not use the service to attempt to obtain dosing, prescriptions, or diagnosis for
          a real person; do not attempt to circumvent its safety rules or its rate limits;
          and do not use it to generate content presented to others as medical advice.
        </p>
      </Section>

      <Section heading="Content and attribution">
        <p>
          Answers are derived from a third-party reference work, which remains the property
          of its publisher and is used here for demonstration. Citations name the work and
          page so that any claim can be traced back to it.
        </p>
      </Section>
    </PageShell>
  );
}
