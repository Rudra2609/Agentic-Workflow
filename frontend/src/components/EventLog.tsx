"use client";

import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import type { StreamStatus } from "@/lib/eventStream";
import { formatTime, shortId } from "@/lib/format";
import type { HmapEvent } from "@/lib/types";

import { Badge, Button, EmptyState, JsonBlock, Mono, cx, inputClass } from "./ui";

const CATEGORY_CLASSES: Record<string, string> = {
  task: "bg-accent-soft text-accent-ink",
  project: "bg-info-soft text-info",
  approval: "bg-warning-soft text-warning",
  agent: "bg-success-soft text-success",
  document: "bg-surface-2 text-fg-2",
  artifact: "bg-surface-2 text-fg-2",
};

export function eventCategory(type: string): string {
  return type.split(".")[0] ?? type;
}

function isFailure(type: string): boolean {
  return /\.(failed|dead_lettered|offline)$/.test(type);
}

/** One-line summary of the interesting `data` fields. */
export function summarizeEvent(e: HmapEvent): string {
  const d = e.data ?? {};
  const parts: string[] = [];
  for (const key of ["name", "capability", "state", "filename", "approved", "reason", "message", "outcome"]) {
    const v = d[key];
    if (v === undefined || v === null || v === "") continue;
    parts.push(`${key}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  }
  return parts.join(" · ");
}

const STATUS_TEXT: Record<StreamStatus, string> = {
  idle: "idle",
  connecting: "connecting…",
  open: "live",
  reconnecting: "reconnecting…",
  closed: "closed",
};

export function EventLog({
  events,
  status,
  onClear,
  showProject = true,
  maxRows = 300,
  label = "Event log",
  heightClass = "max-h-[32rem]",
}: {
  events: readonly HmapEvent[];
  status?: StreamStatus;
  onClear?: () => void;
  showProject?: boolean;
  maxRows?: number;
  label?: string;
  heightClass?: string;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const deferredQuery = useDeferredValue(query);

  const categories = useMemo(() => {
    const set = new Set(events.map((e) => eventCategory(e.event_type)));
    return [...set].sort();
  }, [events]);

  const filtered = useMemo(() => {
    const q = deferredQuery.trim().toLowerCase();
    const out: HmapEvent[] = [];
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const e = events[i]!;
      if (category !== "all" && eventCategory(e.event_type) !== category) continue;
      if (q) {
        const hay = `${e.event_type} ${e.aggregate_id} ${e.project_id ?? ""} ${JSON.stringify(e.data)}`.toLowerCase();
        if (!hay.includes(q)) continue;
      }
      out.push(e);
    }
    return out;
  }, [events, category, deferredQuery]);

  const shown = filtered.slice(0, maxRows);
  const filterId = `${label.replace(/\W+/g, "-").toLowerCase()}-filter`;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <label htmlFor={filterId} className="mb-1 block text-xs font-medium text-muted">
            Filter (type, id, data)
          </label>
          <input
            id={filterId}
            type="search"
            className={inputClass}
            value={query}
            placeholder="e.g. task.completed or a task id"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor={`${filterId}-cat`} className="mb-1 block text-xs font-medium text-muted">
            Category
          </label>
          <select
            id={`${filterId}-cat`}
            className={cx(inputClass, "w-36")}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="all">All</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        {onClear && (
          <Button size="sm" variant="ghost" onClick={onClear} title="Hide current events (new ones keep arriving)">
            Clear
          </Button>
        )}
      </div>
      <p className="mb-2 text-xs text-muted" aria-live="polite">
        {status && (
          <span className={cx("mr-2 font-medium", status === "open" ? "text-success" : "text-warning")}>
            ● {STATUS_TEXT[status]}
          </span>
        )}
        {filtered.length === events.length
          ? `${events.length} event${events.length === 1 ? "" : "s"}`
          : `${filtered.length} of ${events.length} events match`}
        {filtered.length > maxRows ? ` (showing newest ${maxRows})` : ""}
      </p>
      {shown.length === 0 ? (
        <EmptyState title={events.length === 0 ? "No events yet" : "No events match the filter"}>
          {events.length === 0 ? "Events appear here live as the platform works." : null}
        </EmptyState>
      ) : (
        <ol aria-label={label} className={cx("divide-y divide-line overflow-y-auto border-y border-line", heightClass)}>
          {shown.map((e) => (
            <li key={`${e.seq}-${e.event_id}`} className="px-1 py-1.5 text-sm">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <time dateTime={e.occurred_at} className="font-mono text-2xs text-muted tabular-nums">
                  {formatTime(e.occurred_at)}
                </time>
                <Mono className="text-muted">#{e.seq}</Mono>
                <Badge
                  className={cx(
                    isFailure(e.event_type)
                      ? "bg-danger-soft text-danger"
                      : (CATEGORY_CLASSES[eventCategory(e.event_type)] ?? undefined),
                  )}
                >
                  {e.event_type}
                </Badge>
                {e.project_id && e.aggregate_id.startsWith("T-") ? (
                  <Link
                    href={`/projects/${encodeURIComponent(e.project_id)}?task=${encodeURIComponent(e.aggregate_id)}`}
                    className="font-mono text-xs text-fg-2 hover:text-accent-ink"
                    title={`Open task ${e.aggregate_id}`}
                  >
                    {shortId(e.aggregate_id, 12)}
                  </Link>
                ) : (
                  <Mono title={e.aggregate_id}>{shortId(e.aggregate_id, 12)}</Mono>
                )}
                {showProject && e.project_id && (
                  <Link
                    href={`/projects/${encodeURIComponent(e.project_id)}`}
                    className="rounded text-xs text-accent-ink hover:underline"
                    title={e.project_id}
                  >
                    project {shortId(e.project_id)}
                  </Link>
                )}
                <span className="min-w-0 truncate text-xs text-fg-2">{summarizeEvent(e)}</span>
              </div>
              {Object.keys(e.data ?? {}).length > 0 && (
                <div className="mt-1">
                  <JsonBlock value={e} summary="raw event" />
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
