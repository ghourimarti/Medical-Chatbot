import { API_BASE_URL } from "@/lib/env";
import { PageShell, Section } from "@/components/page-shell";
import type { PublicStatus } from "@/lib/contract";

export const metadata = {
  title: "Status — Medical Reference Assistant",
  description: "Whether the assistant is currently able to answer.",
};

// Always fresh: a cached status page is worse than none, because it reports health that
// may have expired. Fetched server-side, so the page ships no client JavaScript.
export const dynamic = "force-dynamic";

const LABELS: Record<PublicStatus["status"], { title: string; body: string; tone: string }> = {
  ok: {
    title: "Operational",
    body: "The assistant can search the reference corpus and generate answers.",
    tone: "text-grounded",
  },
  degraded: {
    title: "Limited service",
    body: "Search is working, but new answers are not being generated right now. Previously answered questions may still return.",
    tone: "text-degraded",
  },
  unavailable: {
    title: "Unavailable",
    body: "The assistant cannot reach part of its own infrastructure and is not answering questions. It will not answer from memory instead.",
    tone: "text-refused",
  },
};

async function load(): Promise<PublicStatus | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/status`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as PublicStatus) : null;
  } catch {
    return null;
  }
}

export default async function StatusPage() {
  const status = await load();

  return (
    <PageShell
      title="Status"
      intro="Live health of the assistant, read from the service itself."
    >
      {status === null ? (
        <div className="rounded-lg border border-line bg-surface-raised p-5">
          <h2 className="font-medium text-refused">Status unavailable</h2>
          <p className="mt-2 text-ink-muted">
            This page could not reach the service. That itself usually means the assistant is
            not answering — treat it as an outage rather than as a reporting glitch.
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-lg border border-line bg-surface-raised p-5">
            <h2 className={`text-lg font-semibold ${LABELS[status.status].tone}`}>
              {LABELS[status.status].title}
            </h2>
            <p className="mt-2 max-w-[68ch] text-ink">{LABELS[status.status].body}</p>
          </div>

          <Section heading="Components">
            <dl className="divide-y divide-line rounded-lg border border-line">
              {[
                ["Reference index", status.checks.vector_store],
                ["Search model", status.checks.embedder],
                ["Answer generation", status.generation_enabled],
              ].map(([label, ok]) => (
                <div key={String(label)} className="flex items-center justify-between px-4 py-2.5">
                  <dt className="text-sm text-ink">{label as string}</dt>
                  <dd
                    className={`text-sm font-medium ${ok ? "text-grounded" : "text-refused"}`}
                  >
                    {ok ? "Available" : "Unavailable"}
                  </dd>
                </div>
              ))}
            </dl>
          </Section>

          <Section heading="Version">
            <p className="text-ink-muted">
              Corpus <code className="text-ink">{status.corpus.version}</code> · index{" "}
              <code className="text-ink">{status.corpus.index_version}</code>. These change
              when the reference material is re-indexed, which can change the answers you
              get for the same question.
            </p>
          </Section>
        </>
      )}
    </PageShell>
  );
}
