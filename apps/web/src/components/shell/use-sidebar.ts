"use client";

import { useCallback, useEffect, useState } from "react";

const KEY = "medbot.sidebar";

/**
 * Sidebar open/closed, split into two independent states on purpose (F1).
 *
 *   collapsed — the DESKTOP preference, persisted. A user who works with it closed keeps
 *               it closed across visits.
 *   drawerOpen — the MOBILE overlay, never persisted. Landing on a page with a drawer
 *               already covering the content would be hostile, and on mobile the sidebar
 *               is a temporary surface rather than a layout choice.
 *
 * Collapsing them into one flag is the obvious shortcut and it is wrong in both
 * directions: a persisted mobile drawer traps the user, and a non-persisted desktop
 * preference forgets itself on every navigation.
 */
export function useSidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // After mount, like the theme toggle: reading storage during render desyncs SSR markup.
  // The flash this could cause is a sidebar width, not a full-page colour inversion, so it
  // does not warrant a second render-blocking inline script.
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(KEY) === "collapsed");
    } catch {
      // Private mode / blocked site data: the default (expanded) is the safe one.
    }
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(KEY, next ? "collapsed" : "expanded");
      } catch {
        /* in-memory only for this session */
      }
      return next;
    });
  }, []);

  // Escape closes the drawer. Registered only while it is open so this does not steal
  // Escape from the rename input or a confirmation prompt the rest of the time.
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  // A drawer open over the page must not let the page behind it scroll — on touch the
  // scroll otherwise "falls through" to the content and the drawer feels broken.
  useEffect(() => {
    if (!drawerOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [drawerOpen]);

  return { collapsed, toggleCollapsed, drawerOpen, setDrawerOpen };
}
