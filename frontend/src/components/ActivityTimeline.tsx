"use client";

/** A continuous, readable timeline of meaningful events (simple mode). Built only from real events. */
import Link from "next/link";

import { formatRelative, formatTime } from "@/lib/format";
import { describeEvent, eventTone, type Tone } from "@/lib/plain";
import type { HmapEvent } from "@/lib/types";

import { cx } from "./ui";

const DOT: Record<Tone, string> = {
  neutral: "bg-line-strong",
  progress: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  muted: "bg-disabled",
};

export interface TimelineEntry {
  event: HmapEvent;
  text: string;
  /** How many identical consecutive events this entry stands for (ledger only; set by the caller). */
  repeats?: number;
}

export function timelineEntries(
  events: readonly HmapEvent[],
  taskTitle?: (taskId: string) => string | undefined,
  limit = 200,
): TimelineEntry[] {
  const out: TimelineEntry[] = [];
  for (let i = events.length - 1; i >= 0 && out.length < limit; i--) {
    const e = events[i]!;
    const text = describeEvent(e, taskTitle);
    if (text) out.push({ event: e, text });
  }
  return out;
}

export function ActivityTimeline({
  entries,
  projectName,
  emptyText = "Nothing has happened yet.",
  variant = "rail",
}: {
  entries: readonly TimelineEntry[];
  /** When given, each entry links to its project (Activity page). */
  projectName?: (projectId: string) => string | undefined;
  emptyText?: string;
  /** rail: dots on a line (project page). ledger: a logbook page, times in the ruled margin (Activity page). */
  variant?: "rail" | "ledger";
}) {
  if (entries.length === 0) return <p className={cx("text-sm text-muted", variant === "ledger" ? "px-5 py-6" : "py-6")}>{emptyText}</p>;
  const projectLink = (e: HmapEvent) => {
    const name = e.project_id && projectName ? projectName(e.project_id) : undefined;
    return name && e.project_id ? (
      <Link href={`/projects/${encodeURIComponent(e.project_id)}`} className="text-fg-2 underline-offset-2 hover:text-accent-ink hover:underline">
        {name}
      </Link>
    ) : null;
  };
  if (variant === "ledger") {
    return (
      <ol>
        {entries.map(({ event: e, text, repeats = 1 }) => {
          const tone = eventTone(e.event_type);
          const link = projectLink(e);
          return (
            <li key={`${e.seq}-${e.event_id}`} className="grid grid-cols-[4.5rem_minmax(0,1fr)] border-b border-line/70 last:border-b-0 sm:grid-cols-[5.5rem_minmax(0,1fr)]">
              <time dateTime={e.occurred_at} title={new Date(e.occurred_at).toLocaleString()} className="py-3 pr-3 text-right text-2xs leading-5 text-muted tabular-nums">
                {formatTime(e.occurred_at)}
              </time>
              <div className="hm-margin flex gap-3 py-3 pr-5 pl-4">
                <span aria-hidden="true" className={cx("mt-1.5 size-2 shrink-0 rounded-full", DOT[tone])} />
                <div className="min-w-0">
                  <p className={cx("text-sm", tone === "danger" ? "text-danger" : "text-fg")}>
                    {text}
                    {repeats > 1 && <span className="ml-1 text-xs text-muted"> {repeats} times</span>}
                  </p>
                  {link && <p className="mt-0.5 text-2xs text-muted">In {link}</p>}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    );
  }
  return (
    <ol className="relative">
      {entries.map(({ event: e, text }, i) => {
        const tone = eventTone(e.event_type);
        const link = projectLink(e);
        return (
          <li key={`${e.seq}-${e.event_id}`} className="relative flex gap-3 pb-4 last:pb-0">
            {i < entries.length - 1 && <span aria-hidden="true" className="absolute top-3 bottom-0 left-[3.5px] w-px bg-line" />}
            <span aria-hidden="true" className={cx("relative z-10 mt-1.5 size-2 shrink-0 rounded-full", DOT[tone])} />
            <div className="min-w-0 flex-1">
              <p className={cx("text-sm", tone === "danger" ? "text-danger" : "text-fg")}>{text}</p>
              <p className="mt-0.5 text-2xs text-muted">
                <time dateTime={e.occurred_at} title={new Date(e.occurred_at).toLocaleString()}>
                  {formatRelative(e.occurred_at)}, at {formatTime(e.occurred_at)}
                </time>
                {link && <> in {link}</>}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
