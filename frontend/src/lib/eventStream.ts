/**
 * Pure state logic for the live event feed (used by `useEventStream`). Kept free of React and WebSocket so it is
 * unit-tested directly.
 *
 * Guarantees:
 *  - events are kept sorted by `seq`, each `seq` at most once (duplicates after a reconnect are dropped);
 *  - at most `cap` events are kept in memory (the oldest are evicted first);
 *  - `lastSeq` is the highest `seq` ever accepted -> the `after_seq` to resume from after a reconnect.
 */
import { toWebSocketUrl } from "./config";
import type { HmapEvent } from "./types";

export type StreamStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

export interface StreamState {
  events: HmapEvent[];
  /** Highest seq accepted so far (0 = nothing yet). Resume point for `after_seq`. */
  lastSeq: number;
  /** event_id of the event with `lastSeq` (used to detect an API restart, which resets seq to 1). */
  lastEventId: string | null;
  status: StreamStatus;
  cap: number;
  /** Duplicates dropped so far (diagnostics). */
  duplicates: number;
  /** Times the history was reset because the API restarted. */
  resets: number;
  /** Consecutive failed connection attempts (0 while connected). */
  attempt: number;
  error: string | null;
}

export type StreamAction =
  | { type: "received"; events: HmapEvent[] }
  | { type: "status"; status: StreamStatus; attempt?: number; error?: string | null }
  | { type: "reset" }
  | { type: "clear" };

export const DEFAULT_HISTORY_CAP = 1000;

export function initialStreamState(cap: number = DEFAULT_HISTORY_CAP): StreamState {
  return {
    events: [],
    lastSeq: 0,
    lastEventId: null,
    status: "idle",
    cap: Math.max(1, Math.floor(cap)),
    duplicates: 0,
    resets: 0,
    attempt: 0,
    error: null,
  };
}

/** Narrow an untrusted WebSocket payload to an event (anything without a numeric seq + event_type is ignored). */
export function parseEvent(raw: unknown): HmapEvent | null {
  let value = raw;
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== "object") return null;
  const e = value as Partial<HmapEvent>;
  if (typeof e.seq !== "number" || !Number.isFinite(e.seq) || typeof e.event_type !== "string") return null;
  return {
    ...e,
    seq: e.seq,
    event_id: typeof e.event_id === "string" ? e.event_id : `seq-${e.seq}`,
    event_type: e.event_type,
    aggregate_id: typeof e.aggregate_id === "string" ? e.aggregate_id : "",
    occurred_at: typeof e.occurred_at === "string" ? e.occurred_at : new Date().toISOString(),
    project_id: typeof e.project_id === "string" ? e.project_id : null,
    data: e.data && typeof e.data === "object" ? e.data : {},
  };
}

/** Merge new events into a sorted, de-duplicated, capped history. */
export function mergeEvents(
  current: readonly HmapEvent[],
  incoming: readonly HmapEvent[],
  cap: number,
): { events: HmapEvent[]; duplicates: number } {
  const seen = new Set(current.map((e) => e.seq));
  const oldestKept = current.length >= cap ? (current[0]?.seq ?? 0) : -Infinity;
  const fresh: HmapEvent[] = [];
  let duplicates = 0;
  for (const e of incoming) {
    if (seen.has(e.seq) || e.seq <= oldestKept) {
      // already have it, or older than everything a full buffer keeps (it would be evicted immediately)
      duplicates += seen.has(e.seq) ? 1 : 0;
      continue;
    }
    seen.add(e.seq);
    fresh.push(e);
  }
  if (fresh.length === 0) return { events: current as HmapEvent[], duplicates };

  const last = current[current.length - 1];
  const inOrder = fresh.every((e, i) => (i === 0 ? !last || e.seq > last.seq : e.seq > fresh[i - 1]!.seq));
  const merged = inOrder ? [...current, ...fresh] : [...current, ...fresh].sort((a, b) => a.seq - b.seq);
  return { events: merged.length > cap ? merged.slice(merged.length - cap) : merged, duplicates };
}

export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  switch (action.type) {
    case "received": {
      if (action.events.length === 0) return state;
      const { events, duplicates } = mergeEvents(state.events, action.events, state.cap);
      let lastSeq = state.lastSeq;
      let lastEventId = state.lastEventId;
      for (const e of action.events) {
        if (e.seq > lastSeq) {
          lastSeq = e.seq;
          lastEventId = e.event_id;
        }
      }
      if (events === state.events && lastSeq === state.lastSeq && duplicates === 0) return state;
      return { ...state, events, lastSeq, lastEventId, duplicates: state.duplicates + duplicates };
    }
    case "status":
      return {
        ...state,
        status: action.status,
        attempt: action.attempt ?? (action.status === "open" ? 0 : state.attempt),
        error: action.error !== undefined ? action.error : action.status === "open" ? null : state.error,
      };
    case "reset":
      // The API restarted (its in-memory feed starts again at seq 1): forget everything and replay from 0.
      return { ...state, events: [], lastSeq: 0, lastEventId: null, resets: state.resets + 1 };
    case "clear":
      // Hide what is on screen but keep the resume point, so nothing old is replayed.
      return { ...state, events: [] };
    default:
      return state;
  }
}

/**
 * Decide how to resume after a reconnect, given `GET /api/events?after_seq=<lastSeq - 1>` (unfiltered).
 *  - the server still has `lastSeq` with the same event_id  -> "resume" (same server, continue after lastSeq)
 *  - it has `lastSeq` with another event_id                  -> "reset"  (API restarted and re-used the seq)
 *  - it only has newer events                                -> "resume" (lastSeq was evicted from its history)
 *  - it has nothing at or after lastSeq                      -> "reset"  (API restarted; its seq is behind ours)
 */
export function classifyResume(
  last: { seq: number; eventId: string | null },
  probe: readonly Pick<HmapEvent, "seq" | "event_id">[],
): "resume" | "reset" {
  if (last.seq <= 0) return "resume";
  const same = probe.find((e) => e.seq === last.seq);
  if (same) return last.eventId === null || same.event_id === last.eventId ? "resume" : "reset";
  return probe.some((e) => e.seq > last.seq) ? "resume" : "reset";
}

/** Exponential backoff with jitter: 0.5 s, 1 s, 2 s, 4 s ... capped at `maxMs`. */
export function backoffDelay(attempt: number, opts: { baseMs?: number; maxMs?: number; random?: () => number } = {}) {
  const base = opts.baseMs ?? 500;
  const max = opts.maxMs ?? 15_000;
  const raw = Math.min(max, base * 2 ** Math.max(0, attempt));
  const jitter = (opts.random ?? Math.random)() * 0.3 * raw; // up to +30 %
  return Math.round(Math.min(max, raw + jitter));
}

/** `base` may be http(s):// (converted) or ws(s)://. The ticket authenticates the socket (single use, 60 s). */
export function buildEventsSocketUrl(
  base: string,
  opts: { afterSeq: number; projectId?: string | null; ticket?: string | null },
) {
  const u = new URL(`${toWebSocketUrl(base)}/api/ws/events`);
  u.searchParams.set("after_seq", String(Math.max(0, Math.floor(opts.afterSeq))));
  if (opts.projectId) u.searchParams.set("project_id", opts.projectId);
  if (opts.ticket) u.searchParams.set("ticket", opts.ticket);
  return u.toString();
}

/** The project feed also contains project-less events (agents); the backend includes them on purpose. */
export function eventMatchesProject(e: HmapEvent, projectId: string | null | undefined): boolean {
  return !projectId || e.project_id === projectId || e.project_id === null;
}
