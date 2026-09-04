import Link from "next/link";

/**
 * Shared shell for the public pages (S10.10).
 *
 * Server component: the page BODIES add about 170 bytes of JS each.
 *
 * Measured, not claimed. An earlier version of this comment said "zero client JavaScript",
 * which the build immediately contradicted: every route reports ~106 kB because the shared
 * LAYOUT holds client components (the theme and density toggles). The page content itself
 * costs almost nothing; the baseline is the price of having those toggles in the header,
 * and it is worth naming rather than rounding away.
 */
export function PageShell({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: string;
  children: React.ReactNode;
}) {
  return (
    <article className="space-y-6">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        {intro && <p className="max-w-[68ch] text-lg text-ink-muted">{intro}</p>}
      </header>
      <div className="prose-page space-y-5">{children}</div>
      <p className="border-t border-line pt-5 text-sm">
        <Link href="/chat" className="text-accent underline underline-offset-2">
          Ask a question
        </Link>
      </p>
    </article>
  );
}

export function Section({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-xl font-semibold">{heading}</h2>
      {children}
    </section>
  );
}
