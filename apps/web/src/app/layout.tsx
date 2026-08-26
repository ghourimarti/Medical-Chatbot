import type { Metadata } from "next";
import { AuthShell } from "@/components/auth/auth-shell";
import { Disclaimer } from "@/components/disclaimer";
import { SiteFooter } from "@/components/site-footer";
import { DensityToggle, PreferencesScript, ThemeToggle } from "@/components/preferences";
import "./globals.css";

export const metadata: Metadata = {
  title: "Medical Reference Assistant",
  description:
    "Answers grounded in a medical reference corpus, with sources shown for every claim.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // suppressHydrationWarning: PreferencesScript mutates <html> dataset before React
  // hydrates, so server and client markup legitimately differ on this one element.
  return (
    <AuthShell>
    <html lang="en" data-density="calm" suppressHydrationWarning>
      <head>
        <PreferencesScript />
      </head>
      <body className="min-h-dvh bg-surface text-ink">
        {/* Skip link: the first tab stop, so a keyboard user is not forced through the
            disclaimer and header on every single page load. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-contrast"
        >
          Skip to content
        </a>

        <Disclaimer />

        <header className="border-b border-line">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-2">
            <span className="text-sm font-medium">Medical Reference Assistant</span>
            <div className="flex items-center gap-1">
              <DensityToggle />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main id="main" className="mx-auto max-w-5xl px-4 py-8">
          {children}
        </main>

        <SiteFooter />
      </body>
    </html>
    </AuthShell>
  );
}
