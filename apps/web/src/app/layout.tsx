import type { Metadata } from "next";
import { AuthShell } from "@/components/auth/auth-shell";
import { Disclaimer } from "@/components/disclaimer";
import { SiteFooter } from "@/components/site-footer";
import { PreferencesScript } from "@/components/preferences";
import { AppShell } from "@/components/shell/app-shell";
import { ConversationsProvider } from "@/lib/conversations-context";
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

        {/* The shell now OWNS the header and <main> (F1). It used to be a centred
            `max-w-5xl` column with the conversation list nested inside one route's page,
            which is why the app read as a web page with a chat on it rather than as a
            product: navigation disappeared on /privacy and was bounded by a column sized
            for prose. The reading measure did not go away — it moved to the CONTENT,
            where `.answer-prose` still caps long-form answers at 68ch. */}
        <ConversationsProvider>
          <AppShell>{children}</AppShell>
        </ConversationsProvider>

        <SiteFooter />
      </body>
    </html>
    </AuthShell>
  );
}
