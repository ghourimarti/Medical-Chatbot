"use client";

import Link from "next/link";

import { DeleteMyData } from "./data-controls";

/**
 * The privacy footer (S10.8).
 *
 * Deliberately on the main surface rather than buried in a settings page. The person most
 * likely to want their health questions deleted is the person who just asked one, and a
 * right-to-erasure control that requires hunting for it satisfies the letter of D18 while
 * missing its point.
 */
export function DataControlsRow({ onDeleted }: { onDeleted: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
      <p className="text-xs text-ink-muted">
        Questions are stored for this session only and removed after 30 days.
      </p>
      <div className="flex items-center gap-3">
        <Link
          href="/privacy"
          className="text-xs text-ink-muted underline underline-offset-2 hover:text-ink"
        >
          What is stored
        </Link>
        <DeleteMyData onDeleted={onDeleted} />
      </div>
    </div>
  );
}
