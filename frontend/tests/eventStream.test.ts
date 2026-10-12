import { describe, expect, it } from "vitest";

import {
  backoffDelay,
  buildEventsSocketUrl,
  classifyResume,
  initialStreamState,
  mergeEvents,
  parseEvent,
  streamReducer,
  type StreamState,
} from "@/lib/eventStream";
import type { HmapEvent } from "@/lib/types";

function ev(seq: number, extra: Partial<HmapEvent> = {}): HmapEvent {
  return {
    seq,
    event_id: `id-${seq}`,
    event_type: "task.created",
    aggregate_id: `t-${seq}`,
    occurred_at: "2026-10-11T10:00:00Z",
    project_id: "p1",
    data: {},
    ...extra,
  };
}

function receive(state: StreamState, ...seqs: number[]): StreamState {
  return streamReducer(state, { type: "received", events: seqs.map((s) => ev(s)) });
}

const seqsOf = (s: StreamState) => s.events.map((e) => e.seq);

describe("stream reducer: dedupe by seq", () => {
  it("drops events it already has (e.g. replayed after a reconnect)", () => {
    let s = receive(initialStreamState(), 1, 2, 3);
    s = receive(s, 2, 3, 4);
    expect(seqsOf(s)).toEqual([1, 2, 3, 4]);
    expect(s.duplicates).toBe(2);
  });

  it("drops duplicates inside one batch", () => {
    const s = receive(initialStreamState(), 5, 5, 6, 6);
    expect(seqsOf(s)).toEqual([5, 6]);
  });

  it("keeps the history sorted when a gap is filled late", () => {
    let s = receive(initialStreamState(), 1, 2, 5);
    s = receive(s, 4, 3);
    expect(seqsOf(s)).toEqual([1, 2, 3, 4, 5]);
    expect(s.lastSeq).toBe(5);
  });

  it("returns the same state object for an all-duplicate empty batch", () => {
    const s = receive(initialStreamState(), 1);
    expect(streamReducer(s, { type: "received", events: [] })).toBe(s);
  });
});

describe("stream reducer: resume point (after_seq)", () => {
  it("tracks the highest seq and its event id", () => {
    const s = receive(initialStreamState(), 3, 9, 7);
    expect(s.lastSeq).toBe(9);
    expect(s.lastEventId).toBe("id-9");
  });

  it("builds the reconnect URL from lastSeq", () => {
    const s = receive(initialStreamState(), 1, 2, 42);
    expect(buildEventsSocketUrl("http://127.0.0.1:8000", { afterSeq: s.lastSeq })).toBe(
      "ws://127.0.0.1:8000/api/ws/events?after_seq=42",
    );
    expect(buildEventsSocketUrl("https://h/", { afterSeq: 0, projectId: "p 1" })).toBe(
      "wss://h/api/ws/events?after_seq=0&project_id=p+1",
    );
  });

  it("'clear' hides events but keeps the resume point; 'reset' forgets both", () => {
    const s = receive(initialStreamState(), 1, 2);
    const cleared = streamReducer(s, { type: "clear" });
    expect(cleared.events).toEqual([]);
    expect(cleared.lastSeq).toBe(2);
    // after a clear, a replay of old events must not come back
    expect(seqsOf(receive(cleared, 3))).toEqual([3]);

    const reset = streamReducer(s, { type: "reset" });
    expect(reset.events).toEqual([]);
    expect(reset.lastSeq).toBe(0);
    expect(reset.resets).toBe(1);
  });

  it("classifies a reconnect probe: resume vs API restart", () => {
    const last = { seq: 10, eventId: "id-10" };
    expect(classifyResume({ seq: 0, eventId: null }, [])).toBe("resume");
    expect(classifyResume(last, [ev(10), ev(11)])).toBe("resume"); // same server
    expect(classifyResume(last, [ev(10, { event_id: "other" })])).toBe("reset"); // seq reused after restart
    expect(classifyResume(last, [])).toBe("reset"); // server is behind us -> restarted
    expect(classifyResume(last, [ev(600)])).toBe("resume"); // ours was evicted from the server's history
  });

  it("status 'open' clears the error and attempt counter", () => {
    let s = streamReducer(initialStreamState(), { type: "status", status: "reconnecting", attempt: 3, error: "boom" });
    expect(s.attempt).toBe(3);
    s = streamReducer(s, { type: "status", status: "open" });
    expect(s).toMatchObject({ status: "open", attempt: 0, error: null });
  });
});

describe("stream reducer: history cap", () => {
  it("keeps only the newest `cap` events", () => {
    let s = initialStreamState(3);
    s = receive(s, 1, 2, 3, 4, 5);
    expect(seqsOf(s)).toEqual([3, 4, 5]);
    s = receive(s, 6);
    expect(seqsOf(s)).toEqual([4, 5, 6]);
    expect(s.lastSeq).toBe(6);
  });

  it("ignores events older than a full buffer instead of re-adding them", () => {
    const merged = mergeEvents([ev(4), ev(5), ev(6)], [ev(2)], 3);
    expect(merged.events.map((e) => e.seq)).toEqual([4, 5, 6]);
  });

  it("never stores more than cap even across many batches", () => {
    let s = initialStreamState(50);
    for (let i = 1; i <= 500; i += 7) s = receive(s, i, i + 1, i + 2);
    expect(s.events.length).toBeLessThanOrEqual(50);
    expect(s.events.at(-1)?.seq).toBe(s.lastSeq);
  });
});

describe("helpers", () => {
  it("parseEvent accepts JSON strings and rejects junk", () => {
    expect(parseEvent(JSON.stringify(ev(3)))?.seq).toBe(3);
    expect(parseEvent("not json")).toBeNull();
    expect(parseEvent({ event_type: "x.y" })).toBeNull();
    expect(parseEvent({ seq: 1, event_type: "x.y" })).toMatchObject({ seq: 1, data: {}, project_id: null });
  });

  it("backoffDelay grows exponentially and is capped", () => {
    const noJitter = { random: () => 0 };
    expect(backoffDelay(0, noJitter)).toBe(500);
    expect(backoffDelay(1, noJitter)).toBe(1000);
    expect(backoffDelay(3, noJitter)).toBe(4000);
    expect(backoffDelay(20, noJitter)).toBe(15_000);
    expect(backoffDelay(20, { random: () => 1 })).toBe(15_000);
  });
});
