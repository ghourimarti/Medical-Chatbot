"use client";

import { useEffect, useState } from "react";
import { AlignJustify, Moon, Rows3, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

export type Density = "calm" | "editorial";
export type Theme = "light" | "dark" | "system";

const DENSITY_KEY = "medbot.density";
const THEME_KEY = "medbot.theme";

/**
 * Runs BEFORE first paint, injected into <head>.
 *
 * Without this, the page renders with defaults and then snaps to the stored preference —
 * a flash of the wrong theme. For a night-time reader a white flash is not a cosmetic
 * nit; it is the thing that makes someone put the phone down.
 *
 * Kept deliberately tiny and dependency-free because it is render-blocking by design.
 */
export function PreferencesScript() {
  const js = `(function(){try{
    var d=localStorage.getItem(${JSON.stringify(DENSITY_KEY)});
    if(d)document.documentElement.dataset.density=d;
    var t=localStorage.getItem(${JSON.stringify(THEME_KEY)});
    if(t&&t!=="system")document.documentElement.dataset.theme=t;
  }catch(e){}})();`;
  return <script dangerouslySetInnerHTML={{ __html: js }} />;
}

function useStored<T extends string>(key: string, fallback: T, attr: string) {
  const [value, setValue] = useState<T>(fallback);

  // Read AFTER mount: reading localStorage during render would desync server and client
  // HTML and trip hydration. The inline script above already prevented the visual flash,
  // so this only has to catch React up to what the DOM already shows.
  useEffect(() => {
    const stored = localStorage.getItem(key) as T | null;
    if (stored) setValue(stored);
  }, [key]);

  function update(next: T, clearWhen?: T) {
    setValue(next);
    localStorage.setItem(key, next);
    if (clearWhen && next === clearWhen) delete document.documentElement.dataset[attr];
    else document.documentElement.dataset[attr] = next;
  }

  return [value, update] as const;
}

/** D27b: Clinical Calm (default) vs Editorial Evidence. One renderer, two layouts. */
export function DensityToggle() {
  const [density, setDensity] = useStored<Density>(DENSITY_KEY, "calm", "density");
  const next: Density = density === "calm" ? "editorial" : "calm";
  const Icon = density === "calm" ? Rows3 : AlignJustify;
  return (
    <button
      onClick={() => setDensity(next)}
      className={cn(
        "inline-flex items-center gap-2 rounded-md px-2 py-1 text-xs",
        "text-ink-muted hover:bg-surface-sunken hover:text-ink",
      )}
      aria-label={`Switch to ${next === "calm" ? "Clinical Calm" : "Editorial Evidence"} layout`}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {density === "calm" ? "Clinical Calm" : "Editorial Evidence"}
    </button>
  );
}

export function ThemeToggle() {
  const [theme, setTheme] = useStored<Theme>(THEME_KEY, "system", "theme");
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => setTheme(next, "system")}
      className="inline-flex items-center gap-2 rounded-md px-2 py-1 text-xs text-ink-muted hover:bg-surface-sunken hover:text-ink"
      aria-label={`Switch to ${next} theme`}
    >
      {theme === "dark" ? (
        <Sun className="size-3.5" aria-hidden="true" />
      ) : (
        <Moon className="size-3.5" aria-hidden="true" />
      )}
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
