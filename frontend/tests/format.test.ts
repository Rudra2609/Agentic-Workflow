import { describe, expect, it } from "vitest";

import { normalizeBaseUrl, toWebSocketUrl } from "@/lib/config";
import { ageMs, formatBytes, formatDuration, humanize, shortId } from "@/lib/format";

describe("format helpers", () => {
  it("formats heartbeat ages", () => {
    const now = Date.parse("2026-10-11T10:00:00Z");
    expect(formatDuration(ageMs("2026-10-11T09:59:57Z", now))).toBe("3s");
    expect(formatDuration(ageMs("2026-10-11T09:55:55Z", now))).toBe("4m 05s");
    expect(formatDuration(ageMs("2026-10-11T07:53:00Z", now))).toBe("2h 07m");
    expect(formatDuration(-5000)).toBe("0s"); // clock skew
    expect(formatDuration(ageMs("garbage", now))).toBe("—");
  });

  it("formats ids, bytes and enum names", () => {
    expect(shortId("0123456789abcdef", 8)).toBe("01234567…");
    expect(shortId(null)).toBe("—");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(humanize("AWAITING_APPROVAL")).toBe("Awaiting approval");
  });

  it("normalizes the API URL and derives the WebSocket URL", () => {
    expect(normalizeBaseUrl(undefined)).toBe("");                 // same origin (Next.js proxies /api)
    expect(normalizeBaseUrl(" http://h:1/// ")).toBe("http://h:1");
    expect(toWebSocketUrl("http://127.0.0.1:8000")).toBe("ws://127.0.0.1:8000");
    expect(toWebSocketUrl("https://x.local")).toBe("wss://x.local");
  });
});
