import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, BookOpenCheck, ShieldAlert, Sparkles } from "lucide-react";

export const metadata: Metadata = {
  title: "Medical Reference Assistant",
  description:
    "Answers drawn from a medical encyclopedia, with every claim cited and every limit stated.",
};

/**
 * The front door (F8).
 *
 * THE HOME PAGE. The app itself moved to `/chat`.
 *
 * I argued against this twice — the product is usable with no account and no preamble
 * (D24), and a landing page puts a click in front of that for every returning visitor.
 * That is a real cost and it is still real. But it was asked for three times, and a
 * front door is a reasonable thing to want for a product people arrive at from a link
 * with no idea what it is. The cost is mitigated by making every path to the app one
 * click and unmissable: the primary button, the header brand, and the sidebar.
 *
 * Server component, no client JS. Every claim below is checkable against behaviour — the
 * corpus is named, the refusals are enumerable, and "says when it does not know" is a
 * threshold in the pipeline, not a disposition.
 */

const PILLARS = [
  {
    icon: BookOpenCheck,
    title: "Every claim is cited",
    body: "Answers come from the Gale Encyclopedia of Medicine, and each one shows the source and page it was drawn from. An uncited answer is a bug here, not a style choice.",
  },
  {
    icon: Sparkles,
    title: "It says when it does not know",
    body: "If the reference material does not cover your question, you get told that. The gap is never filled with something that merely sounds right.",
  },
  {
    icon: ShieldAlert,
    title: "It refuses two things on purpose",
    body: "No diagnosis and no dosages — enforced in the system rather than left to the model. For anything urgent it points you to emergency services instead of answering.",
  },
];

export default function WelcomePage() {
  return (
    <div className="space-y-14 py-6">
      <section className="space-y-6">
        <p className="text-[0.6875rem] font-semibold tracking-[0.08em] text-accent uppercase">
          Medical reference, not medical advice
        </p>
        <h1 className="max-w-[18ch] text-[2.75rem] leading-[1.1] font-semibold tracking-[-0.02em] text-balance">
          Answers you can <span className="text-accent">check</span>, not just read.
        </h1>
        <p className="max-w-[60ch] text-lg leading-relaxed text-ink-muted">
          A reference assistant that answers only from a named medical encyclopedia, shows
          the passages behind every claim, and tells you plainly when the answer is not
          there.
        </p>
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Link
            href="/chat"
            className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-3 text-[0.9375rem] font-medium text-accent-contrast transition-opacity hover:opacity-90"
          >
            Ask a question
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
          <Link
            href="/how-it-works"
            className="inline-flex items-center gap-2 rounded-full border border-line px-5 py-3 text-[0.9375rem] text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
          >
            How it works
          </Link>
        </div>
        {/* No signup wall, stated up front — it is the least expected thing about a
            product like this and the most likely reason someone hesitates. */}
        <p className="text-sm text-ink-muted">
          No account needed. Your conversations are saved to this browser, and you can sign
          in later to keep them.
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        {PILLARS.map(({ icon: Icon, title, body }) => (
          <div key={title} className="lift rounded-xl border border-line bg-surface-raised p-5">
            <Icon className="size-5 text-accent" aria-hidden="true" />
            <h2 className="mt-3 text-[0.9375rem] font-semibold text-ink">{title}</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{body}</p>
          </div>
        ))}
      </section>

      <section className="space-y-4 rounded-xl border border-line bg-surface-sunken p-6">
        <h2 className="text-xl font-semibold tracking-tight">Who it is for</h2>
        <p className="max-w-[68ch] leading-relaxed text-ink-muted">
          Anyone who wants a plain explanation of a condition, a symptom or a treatment, and
          wants to see where that explanation came from. Students, carers, and people trying
          to understand a term they were given in a consultation.
        </p>
        <p className="max-w-[68ch] leading-relaxed text-ink-muted">
          It is <strong className="text-ink">not</strong> for deciding what to do about your
          own health. It cannot examine you, does not know your history, and will decline
          rather than guess. If something is urgent, contact your local emergency services.
        </p>
        <p className="pt-1">
          <Link href="/about" className="text-accent underline underline-offset-4">
            More about how this was built
          </Link>
        </p>
      </section>
    </div>
  );
}
