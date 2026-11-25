import type { Tone } from "@/lib/plain";

import type { Hardware, ModelRow, QuickResult, RouteRecord } from "./types";

export const SUITES = ["extraction", "planning", "critique", "verify", "coding"] as const;

export function gb(value: number | null | undefined): string {
  return value == null ? "–" : `${value.toFixed(1)} GB`;
}

export function pct(value: number | null | undefined): string {
  return value == null ? "–" : `${Math.round(value * 100)}%`;
}

export const STATUS_TONE: Record<ModelRow["spec"]["status"], Tone> = {
  installed: "success",
  available: "neutral",
  missing: "muted",
  disabled: "warning",
};

export const FIT_LABEL: Record<Hardware["feasibility"][number]["fit"], { label: string; tone: Tone }> = {
  fits: { label: "fits", tone: "success" },
  fits_alone: { label: "fits alone", tone: "warning" },
  does_not_fit: { label: "does not fit", tone: "danger" },
  unknown: { label: "unknown", tone: "muted" },
};

/** One line for a decision's outcome. */
export function outcome(r: RouteRecord): { label: string; tone: Tone } {
  if (r.ok === null) return { label: "running", tone: "progress" };
  if (!r.ok) return { label: r.error ? `failed (${r.error})` : "failed", tone: "danger" };
  const local = r.answered_by != null && !r.answered_by.startsWith("groq:") && !r.answered_by.startsWith("gemini:");
  return { label: `answered by ${r.answered_by ?? "?"}`, tone: local ? "warning" : "success" };
}

/** Quick-set results from the bench files, best quality first; incomplete runs last. */
export function quickResults(files: Record<string, unknown>): QuickResult[] {
  const out = Object.entries(files)
    .filter(([name]) => name.startsWith("quick_"))
    .map(([, v]) => v as QuickResult)
    .filter((v) => v && typeof v.model === "string");
  return out.sort((a, b) => (b.coverage - a.coverage) || ((b.quality ?? -1) - (a.quality ?? -1)));
}

export function isCloud(model: string): boolean {
  return model.startsWith("groq:") || model.startsWith("gemini:");
}

/** Width of a 0–1 score bar, in percent (never below a hairline so 0 is visible). */
export function barWidth(score: number | null | undefined): string {
  return `${Math.max(1, Math.round((score ?? 0) * 100))}%`;
}

export function memoryUsed(h: Hardware["hardware"]): number {
  return Math.max(0, h.total_gb - h.free_gb);
}
