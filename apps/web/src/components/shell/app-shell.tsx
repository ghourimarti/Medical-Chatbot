"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { PanelLeft, PanelLeftClose } from "lucide-react";
import { DensityToggle, ThemeToggle } from "@/components/preferences";
import { AccountControls } from "@/components/auth/account-controls";
import { usePathname } from "next/navigation";
import { CommandPalette } from "@/components/shell/command-palette";
import { Sidebar } from "@/components/shell/sidebar";
import { useSidebar } from "@/components/shell/use-sidebar";
import { cn } from "@/lib/utils";

/**
 * The application shell (F1).
 *
 * WHAT CHANGED AND WHY IT MATTERS: the sidebar used to be an `<aside>` INSIDE
 * `page.tsx`, nested in the same `max-w-5xl` reading column as the answer. That is why
 * the app read as "a web page that has a chat on it" rather than as a product — the
 * navigation was a widget on one route, it vanished on `/privacy`, and it was bounded by
 * a column sized for prose. Hoisting it into the layout is the whole difference.
 *
 * The reading measure is NOT abandoned in the process. Long-form answers still need a
 * bounded line length (see `.answer-prose`, 68ch); what changes is that the bound now
 * belongs to the CONTENT, not to the whole application chrome.
 */
export function AppShell({
  children,
  accountsEnabled,
}: {
  children: React.ReactNode;
  accountsEnabled: boolean;
}) {
  const { collapsed, toggleCollapsed, drawerOpen, setDrawerOpen } = useSidebar();
  const pathname = usePathname();
  const drawerRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);

  // Focus moves INTO the drawer when it opens and RETURNS to the button that opened it
  // when it closes. Without the return, a keyboard user is dumped back at the top of the
  // document on every close — the most common way a drawer fails an audit while looking
  // perfectly fine to a mouse user.
  //
  // `wasOpen` is what makes the return conditional, and it is NOT defensive noise. An
  // effect keyed on `drawerOpen` also runs on MOUNT, where the drawer has never been
  // open — so the else-branch fired on every page load and moved focus to the opener
  // button before the user touched anything. On mobile, where that button is rendered,
  // the first Tab then landed on the header link instead of "Skip to content", silently
  // breaking the skip link on every page. Caught by the a11y suite under the `mobile`
  // project; desktop hid it because the button is `md:hidden` there and .focus() on a
  // display:none element is a no-op.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (drawerOpen) {
      drawerRef.current?.focus();
    } else if (wasOpen.current) {
      openerRef.current?.focus({ preventScroll: true });
    }
    wasOpen.current = drawerOpen;
  }, [drawerOpen]);

  return (
    <div className="flex min-h-dvh">
      <CommandPalette />
      {/* ---- Desktop rail: part of the layout, so content sits BESIDE it, never under ---- */}
      <div
        className={cn(
          "hidden shrink-0 border-r border-line bg-surface-sunken md:block",
          "transition-[width] duration-200 ease-out",
        )}
        style={{ width: collapsed ? "var(--sidebar-collapsed-w)" : "var(--sidebar-w)" }}
      >
        <div className="sticky top-0 flex h-dvh flex-col">
          <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
        </div>
      </div>

      {/* ---- Mobile drawer ---- */}
      {drawerOpen && (
        <div className="md:hidden">
          <button
            aria-label="Close navigation"
            onClick={() => setDrawerOpen(false)}
            className="fixed inset-0 bg-[var(--scrim)]"
            style={{ zIndex: "var(--z-overlay)" }}
          />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            tabIndex={-1}
            className={cn(
              "fixed inset-y-0 left-0 w-[var(--sidebar-w)] max-w-[85vw]",
              "border-r border-line bg-surface-sunken shadow-[var(--shadow-lg)] outline-none",
            )}
            style={{ zIndex: "var(--z-overlay)" }}
          >
            <div className="flex h-dvh flex-col">
              <Sidebar collapsed={false} onNavigate={() => setDrawerOpen(false)} />
            </div>
          </div>
        </div>
      )}

      {/* ---- Content column ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="sticky top-0 border-b border-line bg-surface/85 backdrop-blur"
          style={{ zIndex: "var(--z-header)" }}
        >
          <div className="flex items-center gap-2 px-3 py-2">
            <button
              ref={openerRef}
              onClick={() => setDrawerOpen(true)}
              aria-label="Open navigation"
              aria-expanded={drawerOpen}
              className="rounded-md p-1.5 text-ink-muted hover:bg-surface-sunken hover:text-ink md:hidden"
            >
              <PanelLeft className="size-4" aria-hidden="true" />
            </button>

            <button
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!collapsed}
              className="hidden rounded-md p-1.5 text-ink-muted hover:bg-surface-sunken hover:text-ink md:inline-flex"
            >
              {collapsed ? (
                <PanelLeft className="size-4" aria-hidden="true" />
              ) : (
                <PanelLeftClose className="size-4" aria-hidden="true" />
              )}
            </button>

            {/* Brand mark -> the front door at "/". The app is at /chat. */}
            <Link
              href="/"
              className="truncate text-sm font-medium transition-colors hover:text-accent"
            >
              Medical Reference Assistant
            </Link>

            <div className="ml-auto flex items-center gap-1">
              <DensityToggle />
              <ThemeToggle />
              {/* Renders NOTHING when accounts are not configured (D24: the product is
                  fully usable anonymously, and an e2e test pins that). It lives here so
                  that adding a Clerk key is all it takes for sign-in to appear exactly
                  where a user already looks for it. */}
              <AccountControls
                enabled={accountsEnabled}
                onSignedIn={() => {
                  void fetch("/api/v1/auth/claim", { method: "POST" });
                }}
              />
            </div>
          </div>
        </header>

        {/* A CENTRED column, not the full width of the viewport.
            Removing the old `max-w-5xl` wrapper from the layout is what let the sidebar
            become real chrome — but dropping the measure entirely is the other failure
            mode: on a wide display the answer card stretched past 970px and the eye loses
            the start of the next line. `.answer-prose` caps the PROSE at 68ch; this caps
            the card, the heading and the composer with it so the column reads as one
            object. `--content-max` is a token so the transcript and any future surface
            cannot disagree about it. */}
        <main id="main" className="min-w-0 flex-1 px-4 py-8 sm:px-6">
          {/* Keyed on the pathname so React remounts the inner wrapper on navigation and
              the entry animation actually replays. Without the key the class is already
              applied and moving between routes is a hard cut.
              Deliberately SHORT (180ms): navigation should feel instant, and anything
              longer starts to read as waiting rather than settling. */}
          <div
            key={pathname}
            className="page-in mx-auto w-full"
            style={{ maxWidth: "var(--content-max)" }}
          >
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
