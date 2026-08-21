import Link from "next/link";

/**
 * Site footer (S10.10).
 *
 * Safety and Sources are listed FIRST, before Privacy and Terms. On most products the
 * legal pages lead; here the two pages that tell you what the assistant refuses to do and
 * what it actually knows are the ones a user needs, so they get the primary position.
 */
const LINKS = [
  { href: "/how-it-works", label: "How it works" },
  { href: "/safety", label: "Safety & limitations" },
  { href: "/sources", label: "Sources" },
  { href: "/status", label: "Status" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
];

export function SiteFooter() {
  return (
    <footer className="mt-12 border-t border-line">
      <nav
        aria-label="Site information"
        className="mx-auto flex max-w-5xl flex-wrap gap-x-5 gap-y-2 px-4 py-5"
      >
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="text-sm text-ink-muted underline-offset-2 hover:text-ink hover:underline"
          >
            {l.label}
          </Link>
        ))}
      </nav>
    </footer>
  );
}
