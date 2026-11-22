"use client";

/**
 * A small, safe Markdown renderer for generated documents (plan D18, trap T15): only text nodes — no
 * `dangerouslySetInnerHTML`, no raw HTML, links only for http(s) / #anchors. Lines with an ungrounded (or
 * unverified) claim are highlighted, the reasons in the tooltip and under the block.
 */
import { Fragment, type ReactNode } from "react";

import { cx } from "@/components/ui";

import { type Block, type Inline, parseMarkdown } from "./logic";
import type { Claim } from "./types";

export function Inlines({ parts }: { parts: Inline[] }) {
  return (
    <>
      {parts.map((p, i) =>
        p.t === "code" ? (
          <code
            key={i}
            className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.85em]"
          >
            {p.v}
          </code>
        ) : p.t === "strong" ? (
          <strong key={i}>{p.v}</strong>
        ) : p.t === "link" ? (
          <a
            key={i}
            href={p.href}
            rel="noreferrer noopener"
            target="_blank"
            className="text-accent underline"
          >
            {p.v}
          </a>
        ) : (
          <Fragment key={i}>{p.v}</Fragment>
        ),
      )}
    </>
  );
}

function Flag({
  claims,
  children,
}: {
  claims: Claim[] | undefined;
  children: ReactNode;
}) {
  if (!claims?.length) return <>{children}</>;
  const bad = claims.some((c) => c.verdict === "ungrounded");
  const why = claims.map((c) => `${c.kind} ${c.text}: ${c.why}`).join("\n");
  return (
    <div
      data-flag={bad ? "ungrounded" : "unverified"}
      title={why}
      className={cx(
        "rounded-sm border-l-4 pl-2",
        bad
          ? "border-[var(--hm-danger)] bg-[var(--hm-danger-soft)]"
          : "border-[var(--hm-warning)]",
      )}
    >
      {children}
      <p className="mt-0.5 text-2xs text-muted">{why}</p>
    </div>
  );
}

function BlockView({ b, flags }: { b: Block; flags: Map<number, Claim[]> }) {
  switch (b.t) {
    case "heading": {
      const cls = [
        "",
        "text-xl",
        "text-lg",
        "text-base",
        "text-sm",
        "text-sm",
        "text-sm",
      ][b.level];
      return (
        <Flag claims={flags.get(b.line)}>
          <p
            role="heading"
            aria-level={b.level}
            className={cx("mt-3 font-semibold text-fg", cls)}
          >
            <Inlines parts={b.text} />
          </p>
        </Flag>
      );
    }
    case "para":
      return (
        <Flag claims={b.lines.flatMap((n) => flags.get(n) ?? [])}>
          <p className="leading-relaxed text-fg-2">
            <Inlines parts={b.text} />
          </p>
        </Flag>
      );
    case "list": {
      const Tag = b.ordered ? "ol" : "ul";
      return (
        <Tag
          className={cx(
            "ml-5 flex flex-col gap-0.5 text-fg-2",
            b.ordered ? "list-decimal" : "list-disc",
          )}
        >
          {b.items.map((it, i) => (
            <li key={i}>
              <Flag claims={flags.get(it.line)}>
                <Inlines parts={it.text} />
              </Flag>
            </li>
          ))}
        </Tag>
      );
    }
    case "table":
      return (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-xs">
            <thead>
              <tr>
                {b.head.map((c, i) => (
                  <th
                    key={i}
                    className="border-b border-line-strong px-2 py-1 text-left font-medium text-muted"
                  >
                    <Inlines parts={c} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {b.rows.map((r, i) => {
                const f = flags.get(r.line);
                return (
                  <tr
                    key={i}
                    data-flag={f?.length ? "row" : undefined}
                    title={f?.map((c) => `${c.text}: ${c.why}`).join("\n")}
                    className={cx(
                      !!f?.length &&
                        "bg-[var(--hm-danger-soft)] outline outline-1 outline-[var(--hm-danger)]",
                    )}
                  >
                    {r.cells.map((c, j) => (
                      <td
                        key={j}
                        className="border-b border-line/70 px-2 py-1 align-top"
                      >
                        <Inlines parts={c} />
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      );
    case "code": {
      const lines = b.code.split("\n");
      const hit = lines.some((_, i) => flags.has(b.line + i));
      return (
        <pre
          data-lang={b.lang || undefined}
          className={cx(
            "overflow-x-auto rounded-md border bg-surface-2 px-3 py-2 font-mono text-xs leading-relaxed",
            hit ? "border-[var(--hm-danger)]" : "border-line",
          )}
        >
          {lines.map((l, i) => {
            const f = flags.get(b.line + i);
            return (
              <div
                key={i}
                title={f?.map((c) => c.why).join("\n")}
                className={cx(
                  !!f?.length &&
                    "bg-[var(--hm-danger-soft)] text-[var(--hm-danger)]",
                )}
              >
                {l || " "}
              </div>
            );
          })}
        </pre>
      );
    }
    case "quote":
      return (
        <Flag claims={flags.get(b.line)}>
          <blockquote className="border-l-2 border-line pl-3 text-muted">
            <Inlines parts={b.text} />
          </blockquote>
        </Flag>
      );
    case "rule":
      return <hr className="border-line" />;
  }
}

export function Markdown({
  source,
  flags,
}: {
  source: string;
  flags?: Map<number, Claim[]>;
}) {
  const blocks = parseMarkdown(source);
  const f = flags ?? new Map<number, Claim[]>();
  return (
    <div className="flex flex-col gap-2 text-sm">
      {blocks.map((b, i) => (
        <BlockView key={i} b={b} flags={f} />
      ))}
    </div>
  );
}
