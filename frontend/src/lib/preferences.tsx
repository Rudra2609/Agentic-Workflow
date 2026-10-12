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
