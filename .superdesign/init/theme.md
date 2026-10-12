# Theme

## Part 1 - Token summary ("pine & saffron")
Light (`:root`): canvas #e8ece5, sidebar #dde3d9, surface #f5f7f2, surface-2 #e0e6dc, fg #1c2620, fg-2 #3f4d45, muted #66736b, line #ccd4c8, line-strong #b2bdae, accent (saffron fill) #f0b23a, accent-hover #f5be52, accent-edge #b07b12, accent-soft #f6e4b8, accent-ink (text) #7d5300, on-accent #1c2620, focus/info (jade) #2f7a68, success #2c6e45, warning (rust) #a34a14, danger (brick) #a32d24.
Dark (`.dark`): canvas #111814, sidebar #0c120f, surface #17201b, surface-2 #1e2923, fg #e6ece4, fg-2 #b4c0b5, muted #829087, line #25322b, line-strong #34433a, accent #f2b33d, accent-ink #f2b33d, on-accent #1a1408, focus #5ec4a7, success #72cb94, warning #f0935c, danger #f07b6c, info #6cc6ae.
Tailwind utilities map 1:1: bg-canvas, bg-surface, text-fg, text-muted, border-line, bg-accent, text-accent-ink, text-danger, ...
Type: display = Bricolage Grotesque (h1/h2, .font-display), body = Hanken Grotesk, mono = JetBrains Mono (ids only). Scale: text-2xs 11px, xs 12, sm 14, base 16, xl 20, page title 28px, hero 52px.
Radius: inputs/buttons rounded-lg (8px), floating panels rounded-2xl (16px), sign-in card rounded-3xl.
Depth: `.hm-key` tactile keycap (inset highlight + 2px bottom edge, presses down 2px), `.hm-float` lifted panels (large soft shadow). 3D hero: `.hm-stage/.hm-stack/.hm-plate` CSS-3D isometric plates with dropping task blocks.
Rules: no purple/blue, no all-caps labels, boxes only for floating surfaces; content sits on paper with rules.
Breakpoints: Tailwind defaults (sm 640, md 768 sidebar appears, lg 1024).

## Part 2 - Raw source
### `frontend/src/app/globals.css`

```css
@import "tailwindcss";

/*
 * HMAP design tokens — "pine & saffron".
 * Pine ink on fog-sage paper; saffron (workshop tape / brass) for actions; jade for information; rust for warnings;
 * brick for errors. Controls are tactile keycaps with a raised edge; only floating things (inspector, menus, the
 * sign-in card, the hierarchy stack) have real depth. Components use the semantic utilities (bg-surface, text-muted,
 * border-line, text-accent-ink, …), never raw colours. The theme is a class on <html> (`dark`), set before first
 * paint by PREFERENCES_INIT_SCRIPT; feature panels written with Tailwind's `dark:` variant keep working.
 */
@custom-variant dark (&:where(.dark, .dark *));

:root {
  color-scheme: light;
  --hm-canvas: #e8ece5;
  --hm-sidebar: #dde3d9;
  --hm-surface: #f5f7f2;
  --hm-surface-2: #e0e6dc;
  --hm-hover: rgb(28 38 32 / 0.06);
  --hm-selected: rgb(240 178 58 / 0.22);
  --hm-fg: #1c2620;
  --hm-fg-2: #3f4d45;
  --hm-muted: #66736b;
  --hm-line: #ccd4c8;
  --hm-line-strong: #b2bdae;
  /* saffron: fills (buttons, markers); accent-ink: the text-safe version for links */
  --hm-accent: #f0b23a;
  --hm-accent-hover: #f5be52;
  --hm-accent-edge: #b07b12;
  --hm-accent-soft: #f6e4b8;
  --hm-accent-ink: #7d5300;
  --hm-on-accent: #1c2620;
  --hm-focus: #2f7a68;
  --hm-success: #2c6e45;
  --hm-success-soft: #dcebdf;
  --hm-warning: #a34a14;
  --hm-warning-soft: #f5e1d2;
  --hm-danger: #a32d24;
  --hm-danger-soft: #f4dbd6;
  --hm-info: #2f7a68;
  --hm-info-soft: #d8ebe4;
  --hm-disabled: #a2ada4;
  /* depth */
  --hm-key-edge: #aeb9aa;
  --hm-shadow: 28 38 32;
}

:root.dark {
  color-scheme: dark;
  --hm-canvas: #111814;
  --hm-sidebar: #0c120f;
  --hm-surface: #17201b;
  --hm-surface-2: #1e2923;
  --hm-hover: rgb(230 236 228 / 0.06);
  --hm-selected: rgb(242 179 61 / 0.14);
  --hm-fg: #e6ece4;
  --hm-fg-2: #b4c0b5;
  --hm-muted: #829087;
  --hm-line: #25322b;
  --hm-line-strong: #34433a;
  --hm-accent: #f2b33d;
  --hm-accent-hover: #f7c461;
  --hm-accent-edge: #9b6a0c;
  --hm-accent-soft: rgb(242 179 61 / 0.15);
  --hm-accent-ink: #f2b33d;
  --hm-on-accent: #1a1408;
  --hm-focus: #5ec4a7;
  --hm-success: #72cb94;
  --hm-success-soft: rgb(114 203 148 / 0.13);
  --hm-warning: #f0935c;
  --hm-warning-soft: rgb(240 147 92 / 0.13);
  --hm-danger: #f07b6c;
  --hm-danger-soft: rgb(240 123 108 / 0.13);
  --hm-info: #6cc6ae;
  --hm-info-soft: rgb(108 198 174 / 0.13);
  --hm-disabled: #4f5d55;
  --hm-key-edge: #0a0f0c;
  --hm-shadow: 0 0 0;
}

@theme inline {
  --color-canvas: var(--hm-canvas);
  --color-sidebar: var(--hm-sidebar);
  --color-surface: var(--hm-surface);
  --color-surface-2: var(--hm-surface-2);
  --color-hover: var(--hm-hover);
  --color-selected: var(--hm-selected);
  --color-fg: var(--hm-fg);
  --color-fg-2: var(--hm-fg-2);
  --color-muted: var(--hm-muted);
  --color-line: var(--hm-line);
  --color-line-strong: var(--hm-line-strong);
  --color-accent: var(--hm-accent);
  --color-accent-hover: var(--hm-accent-hover);
  --color-accent-soft: var(--hm-accent-soft);
  --color-accent-ink: var(--hm-accent-ink);
  --color-on-accent: var(--hm-on-accent);
  --color-focus: var(--hm-focus);
  --color-success: var(--hm-success);
  --color-success-soft: var(--hm-success-soft);
  --color-warning: var(--hm-warning);
  --color-warning-soft: var(--hm-warning-soft);
  --color-danger: var(--hm-danger);
  --color-danger-soft: var(--hm-danger-soft);
  --color-info: var(--hm-info);
  --color-info-soft: var(--hm-info-soft);
  --color-disabled: var(--hm-disabled);

  --font-sans: var(--font-body), ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-display: var(--font-display-face), var(--font-body), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-code), ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  --text-2xs: 0.6875rem;
  --text-2xs--line-height: 1rem;
}

html {
  -webkit-text-size-adjust: 100%;
}

body {
  background: var(--hm-canvas);
  color: var(--hm-fg);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

h1,
h2,
.font-display {
  font-family: var(--font-display);
  font-optical-sizing: auto;
}

::selection {
  background: var(--hm-accent-soft);
}

dialog::backdrop {
  background: rgb(12 18 15 / 0.55);
  backdrop-filter: blur(2px);
}

:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
  outline: 2px solid var(--hm-focus);
  outline-offset: 2px;
}

/* ---------------------------------------------------------------- tactile keycaps */
/* A raised edge (inset bottom + drop) that presses down on click: the physical feel of a control panel. */
.hm-key {
  position: relative;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 0.35),
    0 2px 0 0 var(--hm-key-edge),
    0 6px 14px -8px rgb(var(--hm-shadow) / 0.55);
  transition:
    transform 90ms ease,
    box-shadow 90ms ease,
    background-color 120ms ease;
}
.hm-key:active:not(:disabled) {
  transform: translateY(2px);
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 0.25),
    0 0 0 0 var(--hm-key-edge),
    0 2px 6px -4px rgb(var(--hm-shadow) / 0.5);
}
.hm-key-accent {
  --hm-key-edge: var(--hm-accent-edge);
}
.hm-key-danger {
  --hm-key-edge: color-mix(in oklab, var(--hm-danger) 60%, black);
}
.dark .hm-key {
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 0.08),
    0 2px 0 0 var(--hm-key-edge),
    0 8px 16px -8px rgb(0 0 0 / 0.8);
}

/* Floating surfaces (inspector, menus, dialogs, sign-in card): lifted off the paper. */
.hm-float {
  box-shadow:
    0 1px 0 rgb(255 255 255 / 0.5) inset,
    0 18px 40px -22px rgb(var(--hm-shadow) / 0.55),
    0 2px 6px -2px rgb(var(--hm-shadow) / 0.18);
}
.dark .hm-float {
  box-shadow:
    0 1px 0 rgb(255 255 255 / 0.05) inset,
    0 24px 48px -20px rgb(0 0 0 / 0.85),
    0 2px 6px -2px rgb(0 0 0 / 0.5);
}

/* ---------------------------------------------------------------- the hierarchy stack (sign-in hero) */
.hm-stage {
  perspective: 1400px;
  perspective-origin: 50% 30%;
}
.hm-stack {
  transform-style: preserve-3d;
  transform: rotateX(var(--hm-tilt-x, 58deg)) rotateZ(var(--hm-tilt-z, -38deg));
  transition: transform 600ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.hm-plate {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
  border-radius: 18px;
  border: 1px solid color-mix(in oklab, var(--hm-line-strong) 80%, transparent);
  background:
    linear-gradient(135deg, rgb(255 255 255 / 0.55), rgb(255 255 255 / 0.12)),
    color-mix(in oklab, var(--hm-surface) 72%, transparent);
  backdrop-filter: blur(3px);
  box-shadow:
    0 30px 50px -30px rgb(var(--hm-shadow) / 0.6),
    0 0 0 1px rgb(255 255 255 / 0.25) inset;
}
.dark .hm-plate {
  background:
    linear-gradient(135deg, rgb(255 255 255 / 0.08), rgb(255 255 255 / 0.01)),
    color-mix(in oklab, var(--hm-surface-2) 80%, transparent);
  box-shadow:
    0 30px 60px -28px rgb(0 0 0 / 0.9),
    0 0 0 1px rgb(255 255 255 / 0.04) inset;
}
.hm-plate.hm-plate-top,
.dark .hm-plate.hm-plate-top {
  background:
    linear-gradient(135deg, rgb(255 255 255 / 0.45), rgb(255 255 255 / 0)),
    color-mix(in oklab, var(--hm-accent) 88%, transparent);
  border-color: var(--hm-accent-edge);
  box-shadow:
    0 30px 50px -26px rgb(var(--hm-shadow) / 0.55),
    0 0 0 1px rgb(255 255 255 / 0.35) inset;
}
.hm-seat {
  border-radius: 9px;
  background: var(--hm-surface);
  border: 1px solid var(--hm-line-strong);
  box-shadow: 0 3px 0 var(--hm-key-edge);
}
/* task blocks travel down through the layers */
.hm-drop {
  transform-style: preserve-3d;
  animation: hm-drop 6s cubic-bezier(0.55, 0, 0.35, 1) infinite;
}
@keyframes hm-drop {
  0% { transform: translateZ(var(--from)); opacity: 0; }
  8% { opacity: 1; }
  45% { transform: translateZ(var(--mid)); }
  55% { transform: translateZ(var(--mid)); }
  92% { transform: translateZ(var(--to)); opacity: 1; }
  100% { transform: translateZ(var(--to)); opacity: 0; }
}
.hm-beam {
  animation: hm-beam 6s ease-in-out infinite;
}
@keyframes hm-beam {
  0%, 100% { opacity: 0.15; }
  40%, 60% { opacity: 0.6; }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  .hm-drop {
    animation: none;
    opacity: 0;
  }
}

```

### `frontend/src/lib/preferences.tsx`

```tsx
"use client";

/**
 * Per-browser preferences: colour theme (light / dark / system) and presentation mode (simple / developer).
 * Stored in localStorage; applied before first paint by PREFERENCES_INIT_SCRIPT (no theme flash). Mode only
 * changes what is shown — never what the user may do (the API enforces permissions).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Theme = "system" | "light" | "dark";
export type Mode = "simple" | "developer";

export const THEME_KEY = "hmap-theme";
export const MODE_KEY = "hmap-mode";

export const PREFERENCES_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");var d=t==="dark"||(t!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);var m=localStorage.getItem("${MODE_KEY}");document.documentElement.dataset.mode=m==="developer"?"developer":"simple";}catch(e){}})();`;

export function readTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function readMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === "developer" ? "developer" : "simple";
  } catch {
    return "simple";
  }
}

export function applyTheme(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

function save(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: the preference still applies to this page */
  }
}

interface Preferences {
  theme: Theme;
  mode: Mode;
  developer: boolean;
  setTheme: (t: Theme) => void;
  setMode: (m: Mode) => void;
}

const PreferencesContext = createContext<Preferences | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");
  const [mode, setModeState] = useState<Mode>("simple");

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after hydration
    setThemeState(readTheme());
    setModeState(readMode());
  }, []);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    save(THEME_KEY, t);
  }, []);
  const setMode = useCallback((m: Mode) => {
    setModeState(m);
    save(MODE_KEY, m);
    document.documentElement.dataset.mode = m;
  }, []);

  const value = useMemo(
    () => ({ theme, mode, developer: mode === "developer", setTheme, setMode }),
    [theme, mode, setTheme, setMode],
  );
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): Preferences {
  const ctx = useContext(PreferencesContext);
  if (!ctx) throw new Error("usePreferences must be used inside <PreferencesProvider>");
  return ctx;
}

```
