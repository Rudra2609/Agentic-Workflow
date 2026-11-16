import { describe, expect, it } from "vitest";

import { baseText, codingEventKey, parseChanges, parseDiff, runTitle, toolLog } from "./logic";
import type { CodingTrace } from "./types";

const DIFF = `--- a/stats.py
+++ b/stats.py
@@ -1,3 +1,4 @@
 mid = len(ordered) // 2
-return ordered[mid]
+if len(ordered) % 2:
+    return ordered[mid]
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+x = 1
\\ No newline at end of file
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-g = 1
`;

describe("parseDiff", () => {
  it("splits a unified diff per file with counts and statuses", () => {
    const files = parseDiff(DIFF);
    expect(files.map((f) => [f.path, f.status, f.added, f.removed])).toEqual([
      ["stats.py", "modified", 2, 1],
      ["new.py", "added", 1, 0],
      ["gone.py", "deleted", 0, 1],
    ]);
    expect(files[0]?.lines.map((l) => l.kind)).toEqual(["hunk", "ctx", "del", "add", "add"]);
    expect(files[1]?.lines.at(-1)?.kind).toBe("meta");
    expect(parseDiff("")).toEqual([]);
  });
});

describe("toolLog", () => {
  it("orders model calls, edits and commands by step", () => {
    const trace = {
      steps: [
        { n: 1, kind: "plan", summary: "fix median", prompt_tokens: 100, completion_tokens: 20, ok: true },
        { n: 2, kind: "edit", summary: "edit attempt 1", prompt_tokens: 200, completion_tokens: 50, ok: false },
      ],
      edits: [{ step: 2, files: [], ok: false, error: "SEARCH was not found", notes: [] }],
      commands: [
        { step: 0, cmd: "python -m py_compile stats.py", exit_code: 0, timed_out: false, duration_s: 0.1, output: "", denied: null },
        { step: 2, cmd: "curl x", exit_code: null, timed_out: false, duration_s: 0, output: "", denied: "'curl' may not run here" },
      ],
    } as unknown as CodingTrace;
    const log = toolLog(trace);
    expect(log.map((e) => e.kind)).toEqual(["command", "step", "step", "edit", "command"]);
    expect(log[3]).toMatchObject({ kind: "edit", ok: false, detail: "refused: SEARCH was not found" });
    expect(log[4]).toMatchObject({ kind: "command", ok: false, detail: "denied: 'curl' may not run here" });
    expect(log[1]).toMatchObject({ label: "Planned the change", tokens: 120 });
  });
});

describe("words and keys", () => {
  it("titles, bases, changes and the event key", () => {
    expect(runTitle("code.implement", 0)).toBe("Code change");
    expect(runTitle("code.revise", 2)).toBe("Revision (round 2)");
    expect(baseText("empty", "tcp_server_client")).toBe("started from the tcp server client template");
    expect(baseText("head", null)).toBe("started from the project's code so far");
    expect(parseChanges("- reject spaces\n\n* log joins \n")).toEqual(["reject spaces", "log joins"]);
    const events = [
      { event_type: "task.progress", seq: 3, data: { capability: "code.implement" } },
      { event_type: "task.progress", seq: 4, data: { capability: "research.run" } },
      { event_type: "code.completed", seq: 9 },
    ];
    expect(codingEventKey(events)).toBe("2:9");
  });
});
