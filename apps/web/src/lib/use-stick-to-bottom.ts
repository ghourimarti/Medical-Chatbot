"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Follow a streaming answer, but STOP the moment the reader scrolls up (F4.4).
 *
 * The naive version — scroll to the bottom on every token — is actively hostile here. A
 * reader who scrolls up to re-read a citation while the answer is still being written gets
 * yanked back down on the next token, and the longer the answer the more violently it
 * fights them. Medical answers are exactly the ones people scroll back through.
 *
 * So "stuck to the bottom" is a STATE the reader controls, not a behaviour we impose:
 * scrolling up releases it, and returning to the bottom (or pressing the button this hook
 * powers) re-engages it.
 */
export function useStickToBottom(active: boolean, dep: unknown) {
  const endRef = useRef<HTMLDivElement>(null);
  const [stuck, setStuck] = useState(true);

  // Reading scroll position from the WINDOW, because the transcript scrolls with the page
  // rather than inside its own overflow container. A scroll container here would trap the
  // page scroll on mobile and break the "never scrolls sideways" mobile guarantee.
  useEffect(() => {
    const onScroll = () => {
      const remaining =
        document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
      // 120px of slack: a reader sitting "at the bottom" is rarely at exactly 0, and
      // sub-pixel rounding on zoomed displays never lands on it.
      setStuck(remaining < 120);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!active || !stuck) return;
    // "auto", not "smooth": at token cadence a smooth scroll never finishes before the
    // next one starts, so the page appears to drift permanently. The jump-to-latest
    // button below is the place for smooth, because it is one discrete action.
    endRef.current?.scrollIntoView({ block: "end", behavior: "auto" });
  }, [active, stuck, dep]);

  const jumpToLatest = useCallback(() => {
    setStuck(true);
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, []);

  return { endRef, stuck, jumpToLatest };
}
