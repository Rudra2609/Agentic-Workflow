"use client";

/**
 * Reconnect-safe live feed over `WS /api/ws/events`.
 *
 *  - On (re)connect it asks for `after_seq = lastSeq`, so the server first replays exactly what was missed and then
 *    streams live events. Events are de-duplicated by `seq`, so overlaps are harmless.
 *  - Before a reconnect it probes `GET /api/events?after_seq=<lastSeq-1>` to notice an API restart (the in-memory
 *    feed restarts at seq 1); in that case the local history is reset and replayed from 0.
 *  - Every (re)connect first fetches a single-use ticket (`POST /api/auth/ws-ticket`): the socket goes straight to
 *    the API, which only streams the signed-in user's events.
 *  - Reconnects use exponential backoff with jitter (0.5 s -> 15 s), reset after a successful open.
 *  - Bursts (e.g. the history replay) are batched into one render every `flushMs`.
 *  - At most `cap` events are kept in memory.
 */
import { useCallback, useEffect, useReducer, useRef } from "react";

import { api, errorMessage, type ApiClient } from "./api";
import { webSocketBase } from "./config";
import {
  DEFAULT_HISTORY_CAP,
  backoffDelay,
  buildEventsSocketUrl,
  classifyResume,
  initialStreamState,
  parseEvent,
  streamReducer,
  type StreamState,
} from "./eventStream";
import type { HmapEvent } from "./types";

type WebSocketCtor = new (url: string) => WebSocket;

export interface UseEventStreamOptions {
  /** Only this project's events (plus project-less ones such as agent events). */
  projectId?: string | null;
  /** Max events kept in memory (default 1000). */
  cap?: number;
  enabled?: boolean;
  /** Injection points for tests. */
  client?: Pick<ApiClient, "baseUrl" | "listEvents"> & Partial<Pick<ApiClient, "wsTicket">>;
  WebSocketImpl?: WebSocketCtor;
  flushMs?: number;
  backoff?: { baseMs?: number; maxMs?: number };
}

export interface EventStream extends StreamState {
  /** Hide the current events (the resume point is kept). */
  clear: () => void;
}

const WS_CONNECTING = 0;

export function useEventStream(options: UseEventStreamOptions = {}): EventStream {
  const {
    projectId = null,
    cap = DEFAULT_HISTORY_CAP,
    enabled = true,
    client = api,
    WebSocketImpl,
    flushMs = 50,
    backoff,
  } = options;
  const baseMs = backoff?.baseMs;
  const maxMs = backoff?.maxMs;

  const [state, dispatch] = useReducer(streamReducer, cap, initialStreamState);
  const lastRef = useRef<{ seq: number; eventId: string | null }>({ seq: 0, eventId: null });
  const keyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const WS: WebSocketCtor | undefined =
      WebSocketImpl ?? (typeof WebSocket === "undefined" ? undefined : (WebSocket as WebSocketCtor));
    if (!WS) return;

    // A different project means a different feed: start from scratch (but not on a StrictMode re-run).
    const key = projectId ?? "*";
    if (keyRef.current !== null && keyRef.current !== key) {
      lastRef.current = { seq: 0, eventId: null };
      dispatch({ type: "reset" });
    }
    keyRef.current = key;

    let stopped = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let flushTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let buffer: HmapEvent[] = [];

    const flush = () => {
      if (flushTimer !== undefined) clearTimeout(flushTimer);
      flushTimer = undefined;
      if (buffer.length === 0) return;
      const batch = buffer;
      buffer = [];
      dispatch({ type: "received", events: batch });
    };

    const scheduleReconnect = (error: string) => {
      if (stopped) return;
      const delay = backoffDelay(attempt, { baseMs, maxMs });
      attempt += 1;
      dispatch({ type: "status", status: "reconnecting", attempt, error });
      retryTimer = setTimeout(() => void connect(), delay);
    };

    const connect = async () => {
      if (stopped) return;
      dispatch({ type: "status", status: attempt === 0 && lastRef.current.seq === 0 ? "connecting" : "reconnecting" });

      const last = { ...lastRef.current };
      if (last.seq > 0) {
        try {
          const probe = await client.listEvents({ afterSeq: last.seq - 1 });
          if (stopped) return;
          if (classifyResume(last, probe) === "reset") {
            buffer = [];
            lastRef.current = { seq: 0, eventId: null };
            dispatch({ type: "reset" });
          }
        } catch (err) {
          if (!stopped) scheduleReconnect(errorMessage(err));
          return;
        }
      }
      if (stopped) return;

      let ticket: string | null = null;
      if (client.wsTicket) {
        try {
          ticket = (await client.wsTicket()).ticket;
        } catch (err) {
          if (!stopped) scheduleReconnect(errorMessage(err));
          return;
        }
        if (stopped) return;
      }

      let ws: WebSocket;
      try {
        const base = client.baseUrl || webSocketBase();
        ws = new WS(buildEventsSocketUrl(base, { afterSeq: lastRef.current.seq, projectId, ticket }));
      } catch (err) {
        scheduleReconnect(errorMessage(err));
        return;
      }
      socket = ws;
      ws.onopen = () => {
        if (socket !== ws) return;
        attempt = 0;
        dispatch({ type: "status", status: "open" });
      };
      ws.onmessage = (msg: MessageEvent) => {
        if (socket !== ws) return;
        const event = parseEvent(msg.data);
        if (!event) return;
        if (event.seq > lastRef.current.seq) lastRef.current = { seq: event.seq, eventId: event.event_id };
        buffer.push(event);
        if (flushTimer === undefined) flushTimer = setTimeout(flush, flushMs);
      };
      ws.onerror = () => {
        /* `close` always follows; reconnect is handled there */
      };
      ws.onclose = () => {
        if (socket !== ws) return;
        socket = null;
        flush();
        scheduleReconnect("Live connection lost");
      };
    };

    void connect();

    return () => {
      stopped = true;
      if (retryTimer !== undefined) clearTimeout(retryTimer);
      flush();
      const ws = socket;
      socket = null;
      if (ws) {
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        if (ws.readyState === WS_CONNECTING) ws.onopen = () => ws.close();
        else {
          ws.onopen = null;
          ws.close();
        }
      }
      dispatch({ type: "status", status: "closed" });
    };
  }, [projectId, enabled, client, WebSocketImpl, flushMs, baseMs, maxMs]);

  const clear = useCallback(() => dispatch({ type: "clear" }), []);
  return { ...state, clear };
}

/**
 * Call `onMatch` (debounced) whenever events newer than the ones already seen satisfy `predicate`.
 * Used to refetch REST data when the live feed says something changed.
 */
export function useEventTrigger(
  events: readonly HmapEvent[],
  predicate: (e: HmapEvent) => boolean,
  onMatch: () => void,
  debounceMs = 250,
): void {
  const seenRef = useRef<number | null>(null);
  const pendingRef = useRef(false);
  const predicateRef = useRef(predicate);
  const onMatchRef = useRef(onMatch);
  useEffect(() => {
    predicateRef.current = predicate;
    onMatchRef.current = onMatch;
  });

  const newest = events.length > 0 ? events[events.length - 1]!.seq : 0;
  useEffect(() => {
    const seen = seenRef.current;
    seenRef.current = newest;
    if (seen === null) return; // first render: the page fetched fresh data anyway
    if (events.some((e) => e.seq > seen && predicateRef.current(e))) pendingRef.current = true;
    if (!pendingRef.current) return;
    const t = setTimeout(() => {
      pendingRef.current = false;
      onMatchRef.current();
    }, debounceMs);
    return () => clearTimeout(t);
    // `events` changes together with `newest`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newest, debounceMs]);
}
