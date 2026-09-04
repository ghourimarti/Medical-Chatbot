"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import { DensityToggle, ThemeToggle } from "@/components/preferences";
import { DeleteMyData } from "@/components/chat/data-controls";
import { Button } from "@/components/ui/button";

/**
 * Settings (F5).
 *
 * This exists because the sidebar previously offered a gear icon labelled "settings" that
 * was a LINK to /how-it-works. A label doing the work of a feature is worse than no
 * feature: someone looking for the theme control clicks it, lands on a prose page, and
 * concludes the product has no settings.
 *
 * A panel rather than a route, deliberately. Settings are a detour from the thing you were
 * doing — a route would push the conversation out of view and put a back-navigation between
 * you and it. Everything here is a control that already existed and was scattered across
 * the header and the footer of one page; this gathers them where a user goes looking.
 *
 * The public pages stay LINKS rather than being inlined. Privacy and safety copy is a legal
 * surface that must be readable, addressable and shareable at its own URL, not trapped in
 * an overlay someone cannot link a relative to.
 */
export function SettingsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<Element | null>(null);

  useEffect(() => {
    if (open) {
      restoreTo.current = document.activeElement;
      panelRef.current?.focus();
    } else if (restoreTo.current instanceof HTMLElement) {
      // Same rule as the drawer and the palette: a dialog that closes without restoring
      // focus drops a keyboard user at the top of the document.
      restoreTo.current.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{ zIndex: "var(--z-overlay)" }}
    >
      <button
        aria-label="Close settings"
        onClick={onClose}
        className="fixed inset-0 bg-[var(--scrim)]"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        tabIndex={-1}
        className="relative w-full max-w-md overflow-hidden rounded-xl border border-line bg-surface-raised shadow-[var(--shadow-lg)] outline-none"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-medium">Settings</h2>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-md p-1 text-ink-muted hover:bg-surface-sunken hover:text-ink"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-5 p-4">
          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-ink-muted uppercase">
              Appearance
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <ThemeToggle />
              <DensityToggle />
            </div>
            <p className="text-xs text-ink-muted">
              Theme follows your system until you choose one here. Density switches between
              the calm reading layout and a denser evidence-first one.
            </p>
          </section>

          <section className="space-y-2 border-t border-line pt-4">
            <h3 className="text-xs font-medium tracking-wide text-ink-muted uppercase">
              Your data
            </h3>
            <p className="text-xs text-ink-muted">
              Questions are stored for this session only and removed after 30 days.
            </p>
            {/* Deletion lives HERE as well as on the chat surface on purpose: it is the
                control people go looking for in settings, and the one that must never be
                hard to find. It reports how many rows went, rather than claiming success. */}
            <DeleteMyData onDeleted={onClose} />
          </section>

          <section className="space-y-2 border-t border-line pt-4">
            <h3 className="text-xs font-medium tracking-wide text-ink-muted uppercase">
              About
            </h3>
            <ul className="grid grid-cols-2 gap-1 text-sm">
              {([
                ["/about", "About"],
                ["/how-it-works", "How it works"],
                ["/safety", "Safety & limitations"],
                ["/sources", "Sources"],
                ["/status", "Status"],
                ["/privacy", "Privacy"],
                ["/terms", "Terms"],
                // `as const` so this is a tuple, not string[]. Without it TS widens the
                // element type and `href` becomes `string | undefined`, which Link rejects.
              ] as const).map(([href, label]) => (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onClose}
                    className="text-ink-muted underline underline-offset-2 hover:text-ink"
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <div className="flex justify-end border-t border-line px-4 py-3">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </div>
  );
}
