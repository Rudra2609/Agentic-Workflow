// @vitest-environment happy-dom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HmapEvent } from "@/lib/types";
import { useEventStream } from "@/lib/useEventStream";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  send(e: HmapEvent) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(e) }));
  }
  drop() {
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  static last() {
    return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!;
  }
}

function ev(seq: number, id = `id-${seq}`): HmapEvent {
  return {
    seq,
    event_id: id,
    event_type: "task.created",
    aggregate_id: "t",
    occurred_at: "2026-10-11T10:00:00Z",
    project_id: "p1",
    data: {},
  };
}

function setup(probe: (afterSeq: number) => HmapEvent[]) {
  FakeWebSocket.instances = [];
  const listEvents = vi.fn(async (q?: { afterSeq?: number }) => probe(q?.afterSeq ?? 0));
  const client = { baseUrl: "http://api.test:8000", listEvents } as never;
  const hook = renderHook(() =>
    useEventStream({
      client,
      WebSocketImpl: FakeWebSocket as unknown as new (url: string) => WebSocket,
      flushMs: 1,
      backoff: { baseMs: 1, maxMs: 5 },
    }),
  );
  return { hook, listEvents };
}

afterEach(() => cleanup());

describe("useEventStream", () => {
  it("connects from seq 0, then resumes after the last seq on reconnect without duplicates", async () => {
    const { hook, listEvents } = setup((after) => [ev(after + 1)]); // server still has our last event
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(FakeWebSocket.last().url).toBe("ws://api.test:8000/api/ws/events?after_seq=0");

    act(() => {
      FakeWebSocket.last().open();
      FakeWebSocket.last().send(ev(1));
      FakeWebSocket.last().send(ev(2));
      FakeWebSocket.last().send(ev(3));
    });
    await waitFor(() => expect(hook.result.current.events.map((e) => e.seq)).toEqual([1, 2, 3]));
    expect(hook.result.current.status).toBe("open");

    act(() => FakeWebSocket.last().drop());
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    expect(listEvents).toHaveBeenCalledWith({ afterSeq: 2 });
    expect(FakeWebSocket.last().url).toBe("ws://api.test:8000/api/ws/events?after_seq=3");

    act(() => {
      FakeWebSocket.last().open();
      FakeWebSocket.last().send(ev(3)); // overlap is harmless
      FakeWebSocket.last().send(ev(4));
    });
    await waitFor(() => expect(hook.result.current.events.map((e) => e.seq)).toEqual([1, 2, 3, 4]));
    expect(hook.result.current.status).toBe("open");
  });

  it("resets and replays from 0 when the API restarted (seq went backwards)", async () => {
    const { hook } = setup(() => []); // restarted server has nothing at/after our seq
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.last().open();
      FakeWebSocket.last().send(ev(7));
    });
    await waitFor(() => expect(hook.result.current.lastSeq).toBe(7));

    act(() => FakeWebSocket.last().drop());
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    expect(FakeWebSocket.last().url).toContain("after_seq=0");
    expect(hook.result.current.resets).toBe(1);
    expect(hook.result.current.events).toEqual([]);
  });

  it("closes the socket on unmount and does not reconnect", async () => {
    const { hook } = setup(() => []);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => FakeWebSocket.last().open());
    hook.unmount();
    expect(FakeWebSocket.last().closed).toBe(true);
    await new Promise((r) => setTimeout(r, 20));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
