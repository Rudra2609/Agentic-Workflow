"use client";

import { useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  Section,
  Spinner,
  Status,
  cx,
  textareaClass,
} from "@/components/ui";
import type { ProjectPanelProps } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

import { ArchitectureGraph } from "./ArchitectureGraph";
import {
  checkMarkdown,
  exportUrl,
  fileUrl,
  getBundle,
  listBundles,
  regenerate,
} from "./client";
import {
  DOC_ORDER,
  DOC_TEXT,
  claimsByKind,
  docsEventKey,
  flaggedLines,
  inline,
  pct,
} from "./logic";
import { Inlines, Markdown } from "./Markdown";
import type {
  Accuracy,
  BundleDetail,
  BundleSummary,
  CheckResult,
  Claim,
  DocName,
} from "./types";

/** Project tab "Docs" (Member 9): the generated documents, every claim checked against the code (ungrounded
 * sentences highlighted with the reason), the examples that were run, Regenerate, and "check a sentence". */
export function DocsPanel({ projectId, events, reload }: ProjectPanelProps) {
  const key = docsEventKey(events);
  const runs = useApiQuery(`docgen:${projectId}:${key}`, (signal) =>
    listBundles(projectId, signal),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const list = runs.data ?? [];
  const current = list.find((r) => r.task_id === selected) ?? list[0];

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Documentation"
        description="The documentation agent writes the README, API reference, architecture, code summaries and report sections from what the code really contains, then checks every technical claim against the code. Anything the code does not support is removed and listed."
      >
        {runs.loading ? (
          <LoadingState label="Loading the documentation…" />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={runs.reload} />
        ) : list.length === 0 ? (
          <EmptyState title="No documentation yet">
            The plan&apos;s documentation step writes it once the code (or the
            research for a report) is ready.
          </EmptyState>
        ) : (
          <ul
            className="grid gap-3 sm:grid-cols-2"
            aria-label="Documentation runs"
          >
            {list.map((r) => (
              <li key={r.task_id}>
                <RunCard
                  run={r}
                  active={current?.task_id === r.task_id}
                  onSelect={() => setSelected(r.task_id)}
                />
              </li>
            ))}
          </ul>
        )}
      </Section>
      {current && (
        <Detail
          key={`${current.task_id}:${current.status}`}
          projectId={projectId}
          summary={current}
          onRegenerate={() => {
            runs.reload();
            reload();
          }}
        />
      )}
      {list.length > 0 && (
        <CheckBox projectId={projectId} taskId={current?.task_id} />
      )}
    </div>
  );
}

function tone(p: number | null): "success" | "warning" | "danger" {
  if (p == null) return "warning";
  return p >= 99.9 ? "success" : p >= 95 ? "warning" : "danger";
}

function RunCard({
  run,
  active,
  onSelect,
}: {
  run: BundleSummary;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cx(
        "flex w-full flex-col gap-1.5 rounded-md border px-3 py-2.5 text-left",
        active
          ? "border-accent bg-selected"
          : "border-line bg-surface hover:bg-hover",
      )}
    >
      <span className="flex items-start justify-between gap-2">
        <span className="text-sm font-semibold text-fg">
          {run.capability === "docs.update"
            ? "Update after a code change"
            : run.mode === "document"
              ? "Report"
              : "Documentation"}
        </span>
        {run.status === "running" ? (
          <Spinner className="size-3 shrink-0" label="writing" />
        ) : (
          <Status
            tone={tone(run.grounded_pct)}
            label={`${pct(run.grounded_pct)} grounded`}
          />
        )}
      </span>
      <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
        <span>{run.documents.length} document(s)</span>
        <span>{run.checked} claims checked</span>
        {run.removed > 0 && (
          <span className="text-danger">{run.removed} removed</span>
        )}
        {run.examples_run > 0 && (
          <span>
            {run.examples_run - run.examples_failed}/{run.examples_run} examples
            ran
          </span>
        )}
        {run.degraded && (
          <span className="text-warning">facts only (no model)</span>
        )}
      </span>
    </button>
  );
}

function Detail({
  projectId,
  summary,
  onRegenerate,
}: {
  projectId: string;
  summary: BundleSummary;
  onRegenerate: () => void;
}) {
  const run = useApiQuery(
    `docgen:one:${projectId}:${summary.task_id}:${summary.status}`,
    (signal) => getBundle(projectId, summary.task_id, signal),
  );
  const [doc, setDoc] = useState<DocName | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (run.loading) return <LoadingState label="Loading the documents…" />;
  if (run.error) return <ErrorState error={run.error} onRetry={run.reload} />;
  const d: BundleDetail | undefined = run.data ?? undefined;
  if (!d) return null;
  const names = DOC_ORDER.filter((n) => d.documents[n] !== undefined);
  const shown: DocName | undefined =
    doc && names.includes(doc) ? doc : names[0];
  const acc = d.accuracy;
  const claims = [...(acc?.claims ?? []), ...(acc?.removed ?? [])];
  const t = d.trace;

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Documents"
        description={`From ${t.source || "—"} · ${t.files} files · updated ${formatDateTime(d.summary.updated_at)}${t.degraded ? " · no model answered: built from the facts only" : ""}`}
        actions={
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || d.summary.status !== "done"}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await regenerate(projectId, d.summary.task_id);
                onRegenerate();
              } catch (e) {
                setErr(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Starting…" : "Regenerate"}
          </Button>
        }
      >
        {err ? <InlineError error={err} /> : null}
        <div
          role="tablist"
          aria-label="Documents"
          className="flex flex-wrap gap-1.5"
        >
          {names.map((n) => (
            <button
              key={n}
              type="button"
              role="tab"
              aria-selected={n === shown}
              title={DOC_TEXT[n].help}
              onClick={() => setDoc(n)}
              className={cx(
                "rounded-md border px-2.5 py-1 text-xs",
                n === shown
                  ? "border-accent bg-selected text-fg"
                  : "border-line text-fg-2 hover:bg-hover",
              )}
            >
              {DOC_TEXT[n].label}
              {flaggedLines(claims, n).size > 0 && (
                <span className="ml-1 text-danger">•</span>
              )}
            </button>
          ))}
        </div>
        {shown && (
          <div className="mt-3 flex flex-col gap-3">
            {shown === "architecture" &&
              d.graph &&
              d.graph.nodes.length > 0 && (
                <ArchitectureGraph
                  nodes={d.graph.nodes}
                  edges={d.graph.edges}
                />
              )}
            <div
              className="max-h-[40rem] overflow-auto rounded-md border border-line bg-surface p-4"
              role="tabpanel"
              aria-label={DOC_TEXT[shown].label}
            >
              <Markdown
                source={d.documents[shown] ?? ""}
                flags={flaggedLines(acc?.claims ?? [], shown)}
              />
            </div>
            <a
              className="self-start text-xs text-accent underline"
              href={fileUrl(projectId, d.summary.task_id, shown)}
              target="_blank"
              rel="noreferrer"
            >
              Download {DOC_TEXT[shown].label} (Markdown)
            </a>
            <ExportLinks
              projectId={projectId}
              taskId={d.summary.task_id}
              svg={shown === "architecture" && !!d.graph?.nodes.length}
              patch={!!t.docstring_patch}
            />
          </div>
        )}
      </Section>
      {(t.changelog?.length ?? 0) > 0 && (
        <Section
          title="Changes since the last documentation"
          description="What changed in the code, so the documents were updated."
        >
          <ul
            className="list-disc pl-5 text-xs text-fg-2"
            aria-label="Changelog"
          >
            {t.changelog!.map((c) => (
              <li key={c}>
                <Inlines parts={inline(c)} />
              </li>
            ))}
          </ul>
        </Section>
      )}
      {acc && <AccuracyView acc={acc} />}
      {t.coverage.length > 0 && (
        <Section
          title="Requirements in the report"
          description="Each requirement and where the code (or the verified research) shows it."
        >
          <ul
            className="flex flex-col gap-1 text-xs"
            aria-label="Requirement coverage"
          >
            {t.coverage.map((c) => (
              <li key={`${c.req_id}:${c.section ?? ""}`} className="flex gap-2">
                <Status
                  tone={c.status === "shown" ? "success" : "warning"}
                  label={c.req_id}
                />
                <span className="text-fg-2">
                  {(c.evidence ?? c.claims ?? []).join("; ") || "not shown yet"}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {(t.notes.length > 0 || t.injected_lines.length > 0) && (
        <Section
          title="Notes"
          description={`Refine rounds: ${t.rounds}${t.stop_reason ? ` (stopped: ${t.stop_reason})` : ""} · model calls: ${t.model_calls}`}
        >
          <ul className="text-xs text-muted" aria-label="Notes">
            {t.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
            {t.injected_lines.map((n) => (
              <li key={n} className="text-warning">
                ignored a line addressed to an AI: {n}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function ExportLinks({
  projectId,
  taskId,
  svg,
  patch,
}: {
  projectId: string;
  taskId: string;
  svg: boolean;
  patch: boolean;
}) {
  const link = "text-xs text-accent underline";
  return (
    <div className="flex flex-wrap gap-3" aria-label="Exports">
      <a className={link} href={exportUrl(projectId, taskId, "site.html")}>
        All documents as one HTML page
      </a>
      {svg && (
        <a
          className={link}
          href={exportUrl(projectId, taskId, "architecture.svg")}
        >
          Architecture (SVG)
        </a>
      )}
      {patch && (
        <a
          className={link}
          href={exportUrl(projectId, taskId, "docstrings.diff")}
          title="The model's summaries as docstrings for functions that have none. Review it, then git apply."
        >
          Suggested docstrings (patch)
        </a>
      )}
    </div>
  );
}

function ClaimRow({ c }: { c: Claim }) {
  return (
    <li className="flex flex-col gap-0.5 border-b border-line/70 py-1.5">
      <span className="flex flex-wrap items-center gap-2">
        <Badge>{c.kind}</Badge>
        <span className="font-mono text-xs text-fg">{c.text}</span>
        <span className="text-2xs text-muted">
          {c.doc}:{c.line} · {c.by}
        </span>
      </span>
      <span className="text-xs text-fg-2">{c.why}</span>
      {c.sentence && c.sentence !== c.text && (
        <span className="text-2xs text-muted">“{c.sentence}”</span>
      )}
    </li>
  );
}

function AccuracyView({ acc }: { acc: Accuracy }) {
  const bad = acc.claims.filter((c) => c.verdict === "ungrounded");
  const unverified = acc.claims.filter((c) => c.verdict === "unverified");
  return (
    <Section
      title="Accuracy"
      description={`${acc.grounded} of ${acc.checked} checkable claims are grounded in the code (${pct(acc.grounded_pct)}).${acc.coverage_pct != null ? ` Public functions and classes described: ${pct(acc.coverage_pct)}.` : ""}`}
    >
      <ul className="flex flex-wrap gap-2 text-xs" aria-label="Claims by type">
        {claimsByKind(acc.claims).map((k) => (
          <li key={k.kind}>
            <Badge>
              {k.kind} {k.grounded}/{k.total}
            </Badge>
          </li>
        ))}
      </ul>
      {acc.removed.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold text-danger">
            Removed: the code does not support these
          </h4>
          <ul aria-label="Removed claims">
            {acc.removed.map((c, i) => (
              <ClaimRow key={i} c={c} />
            ))}
          </ul>
        </div>
      )}
      {bad.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold text-danger">
            Still ungrounded
          </h4>
          <ul>
            {bad.map((c, i) => (
              <ClaimRow key={i} c={c} />
            ))}
          </ul>
        </div>
      )}
      {unverified.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold text-warning">
            Not verified (no code found that shows it)
          </h4>
          <ul>
            {unverified.map((c, i) => (
              <ClaimRow key={i} c={c} />
            ))}
          </ul>
        </div>
      )}
      {acc.examples.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold text-fg">Documented examples</h4>
          <ul className="flex flex-col gap-1 text-xs" aria-label="Examples">
            {acc.examples.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Status
                  tone={
                    e.ok === true
                      ? "success"
                      : e.ok === false
                        ? "danger"
                        : "neutral"
                  }
                  label={
                    e.ok === true
                      ? "ran"
                      : e.ok === false
                        ? "failed"
                        : e.action === "check"
                          ? "checked"
                          : "skipped"
                  }
                />
                <code className="font-mono">{e.code.split("\n")[0]}</code>
                <span className="text-muted">{e.why}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  );
}

function CheckBox({
  projectId,
  taskId,
}: {
  projectId: string;
  taskId?: string;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<CheckResult | null>(null);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Section
      title="Check a sentence"
      description="Paste documentation text: every technical claim in it is checked against this project's code (the rules only, no model)."
    >
      <form
        className="flex flex-col gap-2"
        onSubmit={async (ev) => {
          ev.preventDefault();
          if (!text.trim()) return;
          setBusy(true);
          setErr(null);
          try {
            setOut(await checkMarkdown(projectId, text, taskId));
          } catch (e) {
            setErr(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <textarea
          aria-label="Text to check"
          className={textareaClass}
          value={text}
          placeholder="The server caches messages in Redis and listens on port 6379."
          onChange={(e) => setText(e.target.value)}
        />
        <Button
          type="submit"
          size="sm"
          disabled={busy || !text.trim()}
          className="self-start"
        >
          {busy ? "Checking…" : "Check"}
        </Button>
      </form>
      {err ? <InlineError error={err} /> : null}
      {out && (
        <div className="mt-2 text-xs" aria-label="Check result">
          <p className="text-fg-2">
            {out.accuracy.grounded}/{out.accuracy.checked} claims grounded.
          </p>
          <ul>
            {out.accuracy.claims
              .filter((c) => c.verdict !== "unchecked")
              .map((c, i) => (
                <li key={i} className="flex gap-2">
                  <Status
                    tone={c.verdict === "grounded" ? "success" : "danger"}
                    label={c.verdict}
                  />
                  <span className="font-mono">{c.text}</span>
                  <span className="text-muted">{c.why}</span>
                </li>
              ))}
          </ul>
        </div>
      )}
    </Section>
  );
}
