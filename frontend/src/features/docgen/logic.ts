/**
 * Pure helpers for the Docs tab (unit-tested in logic.test.ts): a small Markdown parser (blocks + inline tokens,
 * no HTML ever), which lines carry an ungrounded claim, the graph layout and the refetch key.
 */
import type { Claim, DocName, GraphEdge, GraphNode } from "./types";

export const DOC_TEXT: Record<DocName, { label: string; help: string }> = {
  readme: {
    label: "README",
    help: "what it is, how to run it, configuration, endpoints, code",
  },
  api: { label: "API", help: "every HTTP endpoint the code defines" },
  architecture: {
    label: "Architecture",
    help: "components and their imports (every arrow is an import)",
  },
  summaries: {
    label: "Code summaries",
    help: "each module and function, citing the code",
  },
  report: { label: "Report", help: "sections for the required deliverables" },
};
export const DOC_ORDER: DocName[] = [
  "readme",
  "api",
  "architecture",
  "summaries",
  "report",
];

// ---------------------------------------------------------------------------------------------- Markdown

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; v: string }
  | { t: "link"; v: string; href: string };

export type Block =
  | { t: "heading"; level: number; text: Inline[]; line: number }
  | { t: "para"; text: Inline[]; line: number; lines: number[] }
  | { t: "list"; ordered: boolean; items: { text: Inline[]; line: number }[] }
  | {
      t: "table";
      head: Inline[][];
      rows: { cells: Inline[][]; line: number }[];
    }
  | { t: "code"; lang: string; code: string; line: number }
  | { t: "quote"; text: Inline[]; line: number }
  | { t: "rule" };

const SAFE_HREF = /^(https?:\/\/|#)/i;

/** Inline tokens: `code`, **strong**, [text](url) (only http(s) or #anchors become links). */
export function inline(text: string): Inline[] {
  const out: Inline[] = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ t: "text", v: text.slice(last, at) });
    if (m[1] !== undefined) out.push({ t: "code", v: m[1] });
    else if (m[2] !== undefined) out.push({ t: "strong", v: m[2] });
    else if (m[3] !== undefined) {
      const href = m[4] ?? "";
      out.push(
        SAFE_HREF.test(href)
          ? { t: "link", v: m[3], href }
          : { t: "text", v: m[3] },
      );
    }
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ t: "text", v: text.slice(last) });
  return out;
}

function cells(row: string): string[] {
  return row
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

/** Blocks with their 1-based source line (the grounding checker reports claims by line). */
export function parseMarkdown(md: string): Block[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i] ?? "";
    const line = raw.trim();
    const n = i + 1;
    if (!line || line.startsWith("<!--")) {
      i++;
      continue;
    }
    const fence = /^```([\w+-]*)/.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? "").trim().startsWith("```"))
        body.push(lines[i++] ?? "");
      i++;
      blocks.push({
        t: "code",
        lang: fence[1] ?? "",
        code: body.join("\n"),
        line: n + 1,
      });
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({
        t: "heading",
        level: (h[1] ?? "#").length,
        text: inline(h[2] ?? ""),
        line: n,
      });
      i++;
      continue;
    }
    if (/^(-{3,}|\*{3,})$/.test(line)) {
      blocks.push({ t: "rule" });
      i++;
      continue;
    }
    if (line.startsWith("|")) {
      const head = cells(line).map(inline);
      const rows: { cells: Inline[][]; line: number }[] = [];
      i++;
      if (/^\|?\s*:?-{2,}/.test((lines[i] ?? "").trim())) i++;
      while (i < lines.length && (lines[i] ?? "").trim().startsWith("|")) {
        rows.push({ cells: cells(lines[i] ?? "").map(inline), line: i + 1 });
        i++;
      }
      blocks.push({ t: "table", head, rows });
      continue;
    }
    const item = /^([-*]|\d+\.)\s+(.*)$/;
    if (item.test(line)) {
      const ordered = /^\d+\./.test(line);
      const items: { text: Inline[]; line: number }[] = [];
      while (i < lines.length && item.test((lines[i] ?? "").trim())) {
        const m = item.exec((lines[i] ?? "").trim());
        items.push({ text: inline(m?.[2] ?? ""), line: i + 1 });
        i++;
      }
      blocks.push({ t: "list", ordered, items });
      continue;
    }
    if (line.startsWith(">")) {
      blocks.push({
        t: "quote",
        text: inline(line.replace(/^>\s?/, "")),
        line: n,
      });
      i++;
      continue;
    }
    const para: string[] = [];
    const nums: number[] = [];
    while (i < lines.length) {
      const l = (lines[i] ?? "").trim();
      if (!l || /^(#{1,6}\s|```|\||[-*]\s|\d+\.\s|>)/.test(l)) break;
      para.push(l);
      nums.push(i + 1);
      i++;
    }
    blocks.push({
      t: "para",
      text: inline(para.join(" ")),
      line: n,
      lines: nums,
    });
  }
  return blocks;
}

/** Line -> the reasons of every ungrounded (or unverified) claim on it, for one document. */
export function flaggedLines(
  claims: readonly Claim[],
  doc: string,
): Map<number, Claim[]> {
  const out = new Map<number, Claim[]>();
  for (const c of claims) {
    if (
      c.doc !== doc ||
      (c.verdict !== "ungrounded" && c.verdict !== "unverified")
    )
      continue;
    out.set(c.line, [...(out.get(c.line) ?? []), c]);
  }
  return out;
}

export function claimsByKind(
  claims: readonly Claim[],
): { kind: string; grounded: number; total: number }[] {
  const m = new Map<string, { grounded: number; total: number }>();
  for (const c of claims) {
    if (c.verdict === "unchecked") continue;
    const row = m.get(c.kind) ?? { grounded: 0, total: 0 };
    row.total++;
    if (c.verdict === "grounded") row.grounded++;
    m.set(c.kind, row);
  }
  return [...m.entries()]
    .map(([kind, v]) => ({ kind, ...v }))
    .sort((a, b) => b.total - a.total);
}

export function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 10) / 10} %`;
}

// ------------------------------------------------------------------------------------------- graph layout

export const NODE_W = 180;
export const NODE_H = 44;

/** Left-to-right layers: a node sits one column right of what imports it (cycles cut after N rounds). */
export function layoutGraph(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
): Map<string, { x: number; y: number }> {
  const level = new Map<string, number>(nodes.map((n) => [n.id, 0]));
  const comp = edges.filter((e) => e.kind !== "uses");
  for (let round = 0; round < nodes.length; round++) {
    let moved = false;
    for (const e of comp) {
      const want = (level.get(e.from) ?? 0) + 1;
      if (want > (level.get(e.to) ?? 0) && want < nodes.length) {
        level.set(e.to, want);
        moved = true;
      }
    }
    if (!moved) break;
  }
  const maxComp = Math.max(
    0,
    ...nodes
      .filter((n) => n.kind === "component")
      .map((n) => level.get(n.id) ?? 0),
  );
  for (const n of nodes)
    if (n.kind !== "component") level.set(n.id, maxComp + 1);
  const rows = new Map<number, number>();
  const pos = new Map<string, { x: number; y: number }>();
  for (const n of nodes) {
    const col = level.get(n.id) ?? 0;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    pos.set(n.id, { x: col * (NODE_W + 60), y: row * (NODE_H + 24) });
  }
  return pos;
}

/** Changes when a docs task moves (refetch key): docs.completed events and task events that mention docs.*. */
export function docsEventKey(
  events: readonly {
    event_type: string;
    seq: number;
    data?: Record<string, unknown>;
  }[],
): string {
  const mine = events.filter(
    (e) =>
      e.event_type === "docs.completed" ||
      (e.event_type.startsWith("task.") &&
        /docs\.(generate|update)/.test(JSON.stringify(e.data ?? {}))),
  );
  return `${mine.length}:${mine.at(-1)?.seq ?? 0}`;
}
