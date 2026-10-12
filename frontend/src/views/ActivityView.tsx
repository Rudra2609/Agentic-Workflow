"use client";

/**
 * Activity across the user's projects (the API only streams events of their own projects plus platform events).
 * Simple: a logbook, one folder per day, times in the ruled margin. Developer: the full event stream with filters,
 * sequence numbers and raw data.
 */
import { useId, type ReactNode } from "react";

import { ActivityTimeline, timelineEntries, type TimelineEntry } from "@/components/ActivityTimeline";
import { useWorkspace } from "@/components/AppShell";
import { useGlobalEvents } from "@/components/EventStreamProvider";
import { EventLog } from "@/components/EventLog";
import { PageHeader, Status } from "@/components/ui";
import type { StreamStatus } from "@/lib/eventStream";
import { usePreferences } from "@/lib/preferences";

const CONNECTION: Record<StreamStatus, { tone: "success" | "warning" | "danger" | "neutral"; label: string }> = {
  idle: { tone: "neutral", label: "Starting…" },
  connecting: { tone: "warning", label: "Connecting…" },
  open: { tone: "success", label: "Live" },
  reconnecting: { tone: "warning", label: "Reconnecting…" },
  closed: { tone: "danger", label: "Disconnected" },
};

function dayLabel(iso: string, now: Date): string {
  const d = new Date(iso);
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(now) - start(d)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

/**
 * Entries are newest first, so each day is one consecutive run. Identical consecutive lines (say, nine workers going
 * offline at once) become one line with a count; the newest of them is kept.
 */
function byDay(entries: readonly TimelineEntry[]): { day: string; entries: TimelineEntry[] }[] {
  const now = new Date();
  const out: { day: string; entries: TimelineEntry[] }[] = [];
  for (const entry of entries) {
    const day = dayLabel(entry.event.occurred_at, now);
    const last = out.at(-1);
    const prev = last?.day === day ? last.entries.at(-1) : undefined;
    if (prev && prev.text === entry.text && prev.event.project_id === entry.event.project_id) prev.repeats = (prev.repeats ?? 1) + 1;
    else if (last?.day === day) last.entries.push({ ...entry });
    else out.push({ day, entries: [{ ...entry }] });
  }
  return out;
}

function DayFolder({ day, children }: { day: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="hm-folder-tab text-xs text-fg">
        {day}
      </h2>
      <div className="hm-clipped rounded-[3px] rounded-tl-none">{children}</div>
    </section>
  );
}

export function ActivityView() {
  const { developer } = usePreferences();
  const stream = useGlobalEvents();
  const { projects } = useWorkspace();
  const names = new Map((projects.data ?? []).map((p) => [p.project_id, p.name]));
  const conn = CONNECTION[stream.status];
  return (
    <>
      <PageHeader
        title="Activity"
        subtitle={developer ? "Every event your projects produced, live. Reconnects resume from the last sequence number seen." : "What happened across your projects, newest first."}
        actions={
          <span className="flex flex-col items-end">
            <Status tone={conn.tone} label={conn.label} live={stream.status === "open"} />
            {stream.status !== "open" && stream.error && <span className="mt-0.5 text-2xs text-muted">{stream.error}</span>}
          </span>
        }
      />
      {stream.status !== "open" && stream.events.length > 0 && (
        <p className="mb-4 text-xs text-warning">Updates are paused while the connection is restored; what you see may be out of date.</p>
      )}
      {developer ? (
        <EventLog events={stream.events} status={stream.status} onClear={stream.clear} label="All events" heightClass="max-h-[70vh]" />
      ) : (
        <Logbook entries={timelineEntries(stream.events, undefined, 300)} projectName={(id) => names.get(id)} />
      )}
    </>
  );
}

function Logbook({ entries, projectName }: { entries: readonly TimelineEntry[]; projectName: (id: string) => string | undefined }) {
  const days = byDay(entries);
  if (days.length === 0) {
    return (
      <DayFolder day="Today">
        <ActivityTimeline variant="ledger" entries={[]} emptyText="Nothing has happened yet. Activity from your projects appears here as it happens." />
      </DayFolder>
    );
  }
  return (
    <div className="space-y-8">
      {days.map((d) => (
        <DayFolder key={d.day} day={d.day}>
          <ActivityTimeline variant="ledger" entries={d.entries} projectName={projectName} />
        </DayFolder>
      ))}
    </div>
  );
}
