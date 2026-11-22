import { describe, expect, it } from "vitest";

import {
  claimsByKind,
  docsEventKey,
  flaggedLines,
  inline,
  layoutGraph,
  parseMarkdown,
} from "./logic";
import type { Claim } from "./types";

const claim = (o: Partial<Claim>): Claim => ({
  kind: "TECH",
  text: "Redis",
  verdict: "ungrounded",
  why: "no redis",
  doc: "readme",
  sentence: "",
  line: 3,
  by: "rule",
  evidence: "",
  ...o,
});

describe("markdown parser", () => {
  it("parses blocks with their source lines", () => {
    const md =
      "# Title\n\nA para\nstill para.\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```bash\nmake demo\n```\n";
    const b = parseMarkdown(md);
    expect(b.map((x) => x.t)).toEqual([
      "heading",
      "para",
      "list",
      "table",
      "code",
    ]);
    expect(b[1]).toMatchObject({ line: 3, lines: [3, 4] });
    expect(b[3]).toMatchObject({ rows: [{ line: 11 }] });
    expect(b[4]).toMatchObject({ lang: "bash", code: "make demo", line: 14 });
  });

  it("never makes unsafe links and keeps raw HTML as text", () => {
    expect(
      inline("[x](javascript:alert(1)) and [y](https://a.test) `c` **b**"),
    ).toEqual([
      { t: "text", v: "x" },
      { t: "text", v: ") and " },

      { t: "link", v: "y", href: "https://a.test" },
      { t: "text", v: " " },
      { t: "code", v: "c" },
      { t: "text", v: " " },
      { t: "strong", v: "b" },
    ]);
    const b = parseMarkdown("<img src=x onerror=alert(1)>");
    expect(b[0]).toMatchObject({
      t: "para",
      text: [{ t: "text", v: "<img src=x onerror=alert(1)>" }],
    });
  });
});

describe("claims", () => {
  it("flags lines of one document only and groups by kind", () => {
    const cs = [
      claim({}),
      claim({ doc: "api", line: 3 }),
      claim({ verdict: "grounded", line: 4 }),
      claim({ verdict: "unverified", line: 5, kind: "BEHAVIOUR" }),
      claim({ verdict: "unchecked", kind: "COMMAND" }),
    ];
    expect([...flaggedLines(cs, "readme").keys()]).toEqual([3, 5]);
    expect(claimsByKind(cs)).toEqual([
      { kind: "TECH", grounded: 1, total: 3 },
      { kind: "BEHAVIOUR", grounded: 0, total: 1 },
    ]);
  });
});

describe("graph layout and event key", () => {
  it("puts imported components to the right and libraries last, survives cycles", () => {
    const pos = layoutGraph(
      [
        { id: "a", label: "a", kind: "component" },
        { id: "b", label: "b", kind: "component" },
        { id: "lib", label: "x", kind: "library" },
      ],
      [
        { from: "a", to: "b", count: 1 },
        { from: "b", to: "a", count: 1 },
        { from: "a", to: "lib", count: 1, kind: "uses" },
      ],
    );
    expect(pos.get("lib")!.x).toBeGreaterThan(
      Math.max(pos.get("a")!.x, pos.get("b")!.x),
    );
  });

  it("changes on docs events only", () => {
    const ev = [
      {
        event_type: "task.completed",
        seq: 1,
        data: { capability: "test.run" },
      },
    ];
    expect(docsEventKey(ev)).toBe("0:0");
    expect(
      docsEventKey([...ev, { event_type: "docs.completed", seq: 7 }]),
    ).toBe("1:7");
  });
});
