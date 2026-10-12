"use client";

/** Short confirmations ("Saved", "Project archived"). Announced politely to screen readers; auto-dismissed. */
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { cx } from "./ui";

interface ToastItem {
  id: number;
  message: string;
  tone: "neutral" | "danger";
}

const ToastContext = createContext<((message: string, tone?: ToastItem["tone"]) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const push = useCallback((message: string, tone: ToastItem["tone"] = "neutral") => {
    const id = next.current++;
    setItems((cur) => [...cur.slice(-2), { id, message, tone }]);
    setTimeout(() => setItems((cur) => cur.filter((t) => t.id !== id)), 4000);
  }, []);
  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
        {items.map((t) => (
          <div
            key={t.id}
            className={cx(
              "pointer-events-auto rounded-md px-3.5 py-2 text-sm shadow-lg",
              t.tone === "danger" ? "bg-danger text-white dark:text-canvas" : "bg-fg text-canvas",
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (message: string, tone?: "neutral" | "danger") => void {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
