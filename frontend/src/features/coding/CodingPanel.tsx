"use client";

import { useState } from "react";

import { Badge, Button, EmptyState, ErrorState, InlineError, LoadingState, Mono, Section, Spinner, Status, cx, textareaClass } from "@/components/ui";
import type { ProjectPanelProps } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

import { getRun, listRuns, requestChanges, workspaceZipUrl } from "./client";
import { CHECK_TONE, OUTCOME_TEXT, STOP_TEXT, baseText, codingEventKey, parseChanges, parseDiff, runTitle, toolLog } from "./logic";
import type { DiffFile, LogEntry } from "./logic";
import type { RunDetail, RunSummary } from "./types";

/** Project tab "Coding" (Member 7): each coding step's live tool-call log, the diff, command output, the checks, and
 * a "Request changes" box that starts a revision. */
export function CodingPanel({ projectId, events, reload }: ProjectPanelProps) {
  const runs = useApiQuery(`coding:${projectId}:${codingEventKey(events)}`, (signal) => listRuns(projectId, signal));
  const [selected, setSelected] = useState<string | null>(null);
  const list = runs.data ?? [];
  const current = list.find((r) => r.task_id === selected) ?? list[0];

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Coding"
        description="The coding agent starts from the project's code (or a template), finds the files to change, edits them, runs the checks in a locked-down folder and fixes what fails."
      >
        {runs.loading ? (
          <LoadingState label="Loading the coding steps…" />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={runs.reload} />
        ) : list.length === 0 ? (
          <EmptyState title="No code yet">The plan&apos;s design and implementation steps write code once research is done.</EmptyState>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Coding steps">
            {list.map((r) => (
              <li key={r.task_id}>
                <RunCard run={r} active={current?.task_id === r.task_id} onSelect={() => setSelected(r.task_id)} />
              </li>
            ))}
          </ul>
        )}
      </Section>
      {current && (
        <Detail
          key={`${current.task_id}:${current.status}:${current.model_calls}:${current.commands}`}
          projectId={projectId}
          summary={current}
          onRevised={() => {
            runs.reload();
            reload();
          }}
        />
      )}
    </div>
  );
}

function OutcomeChip({ run }: { run: RunSummary }) {
  if (run.status === "running") return <Spinner className="size-3 shrink-0" label="coding" />;
  const o = run.outcome ? OUTCOME_TEXT[run.outcome] : null;
  return o ? <Status tone={o.tone} label={o.label} title={o.help} /> : <Badge>{run.stop_reason || "done"}</Badge>;
}

function RunCard({ run, active, onSelect }: { run: RunSummary; active: boolean; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} aria-pressed={active} className={cx("flex w-full flex-col gap-1.5 rounded-md border px-3 py-2.5 text-left", active ? "border-accent bg-selected" : "border-line bg-surface hover:bg-hover")}>
      <span className="flex items-start justify-between gap-2">
        <span className="text-sm font-semibold text-fg">{runTitle(run.capability, run.revision_round)}</span>
        <OutcomeChip run={run} />
      </span>
      <span className="line-clamp-2 text-xs text-fg-2">{run.objective}</span>
      <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
        <span>
          {run.files_changed.length} file{run.files_changed.length === 1 ? "" : "s"} changed
        </span>
        {Object.entries(run.checks).map(([name, status]) => (
          <span key={name} className={status === "failed" ? "text-danger" : status === "passed" ? "text-success" : undefined}>
            {name} {status}
          </span>
        ))}
        {run.flags.length > 0 && <span className="text-warning">{run.flags.length} suspicious line(s) treated as data</span>}
      </span>
    </button>
  );
}

function Detail({ projectId, summary, onRevised }: { projectId: string; summary: RunSummary; onRevised: () => void }) {
  const run = useApiQuery(`coding:run:${projectId}:${summary.task_id}:${summary.status}:${summary.model_calls}:${summary.commands}`, (signal) =>
    getRun(projectId, summary.task_id, signal),
  );
  if (run.loading) return <LoadingState label="Loading the coding step…" />;
  if (run.error) return <ErrorState error={run.error} onRetry={run.reload} />;
  const d = run.data;
  if (!d) return null;
  const t = d.trace;
  return (
    <div className="flex flex-col gap-6">
      <Section
        title={runTitle(d.summary.capability, d.summary.revision_round)}
        description={`${baseText(t.base, t.template)} · stopped because ${STOP_TEXT[t.stop_reason] ?? (t.stop_reason || "it is still running")} · ${d.summary.model_calls} model calls, ${d.summary.tokens.toLocaleString()} tokens · updated ${formatDateTime(d.summary.updated_at)}`}
        actions={
          d.summary.status === "done" ? (
            <a className="text-xs text-accent underline" href={workspaceZipUrl(projectId, d.summary.task_id)} download>
              Download the code
            </a>
          ) : null
        }
      >
        <p className="text-sm text-fg">{t.objective}</p>
        {t.acceptance_criteria.length > 0 && (
          <ul className="mt-2 list-disc pl-5 text-xs text-fg-2" aria-label="Acceptance criteria">
            {t.acceptance_criteria.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap gap-2" aria-label="Checks">
          {t.checks.map((c) => (
            <Status key={c.name} tone={CHECK_TONE[c.status]} label={`${c.name}: ${c.status}`} title={c.detail || undefined} />
          ))}
        </div>
        {t.plan?.summary && <p className="mt-3 text-xs text-fg-2">Plan: {t.plan.summary}</p>}
        {t.flags.length > 0 && (
          <p className="mt-2 text-xs text-warning">
            Lines that talk to an AI were found in {t.flags.join(", ")}. They were treated as data, never as instructions.
          </p>
        )}
        {t.notes.length > 0 && (
          <ul className="mt-2 text-xs text-muted" aria-label="Notes">
            {t.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Tool calls" description="What the agent did, in order: model calls, edits (and why one was refused), and every command it ran.">
        <ToolLog entries={toolLog(t)} running={t.status === "running"} />
      </Section>
      <Section title="Changes" description={d.diff ? `${parseDiff(d.diff).length} file(s) in this step's diff.` : "This step changed no file."}>
        <DiffView files={parseDiff(d.diff)} />
      </Section>
      {d.summary.status === "done" && <RequestChanges projectId={projectId} detail={d} onDone={onRevised} />}
    </div>
  );
}

function ToolLog({ entries, running }: { entries: LogEntry[]; running: boolean }) {
  if (entries.length === 0) return <p className="text-xs text-muted">{running ? "Starting…" : "Nothing recorded."}</p>;
  return (
    <ol className="flex flex-col gap-1.5" aria-label="Tool-call log">
      {entries.map((e, i) => (
        <li key={i} className="rounded border border-line/70 px-2.5 py-1.5 text-xs">
          {e.kind === "step" ? (
            <span className="flex flex-wrap items-baseline gap-2">
              <Badge>model</Badge>
              <span className={cx("font-medium", e.ok ? "text-fg" : "text-danger")}>{e.label}</span>
              <span className="text-fg-2">{e.detail}</span>
              <span className="text-muted">{e.tokens} tokens</span>
            </span>
          ) : e.kind === "edit" ? (
            <span className="flex flex-wrap items-baseline gap-2">
              <Badge>edit</Badge>
              <span className={e.ok ? "text-fg-2" : "text-danger"}>{e.detail}</span>
            </span>
          ) : (
            <details>
              <summary className="flex cursor-pointer flex-wrap items-baseline gap-2">
                <Badge>run</Badge>
                <Mono>{e.cmd}</Mono>
                <span className={e.ok ? "text-success" : "text-danger"}>{e.detail}</span>
              </summary>
              <pre className="mt-1.5 max-h-72 overflow-auto rounded bg-surface-2 p-2 text-[11px] leading-snug whitespace-pre-wrap">{e.output || "(no output)"}</pre>
            </details>
          )}
        </li>
      ))}
      {running && (
        <li className="text-xs text-muted">
          <Spinner className="size-3" label="working" /> working…
        </li>
      )}
    </ol>
  );
}

const LINE_CLASS: Record<string, string> = {
  add: "bg-success-soft text-fg",
  del: "bg-danger-soft text-fg",
  hunk: "text-accent",
  meta: "text-muted",
  ctx: "text-fg-2",
};
const SIGN: Record<string, string> = { add: "+", del: "-", ctx: " ", hunk: "", meta: "" };

function DiffView({ files }: { files: DiffFile[] }) {
  if (files.length === 0) return null;
  return (
    <div className="flex flex-col gap-3" aria-label="Diff">
      {files.map((f) => (
        <details key={f.path} open className="rounded border border-line">
          <summary className="flex cursor-pointer flex-wrap items-baseline gap-2 px-2.5 py-1.5 text-xs">
            <Mono>{f.path}</Mono>
            <Badge>{f.status}</Badge>
            <span className="text-success">+{f.added}</span>
            <span className="text-danger">-{f.removed}</span>
          </summary>
          <pre className="max-h-[32rem] overflow-auto border-t border-line text-[11px] leading-snug">
            {f.lines.map((l, i) => (
              <div key={i} className={cx("px-2.5 whitespace-pre", LINE_CLASS[l.kind])}>
                {SIGN[l.kind]}
                {l.text}
              </div>
            ))}
          </pre>
        </details>
      ))}
    </div>
  );
}

function RequestChanges({ projectId, detail, onDone }: { projectId: string; detail: RunDetail; onDone: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [started, setStarted] = useState<string | null>(null);
  const changes = parseChanges(text);
  return (
    <Section title="Request changes" description="One change per line. The agent revises this step's code (a new coding step, starting from the project's current code).">
      <label htmlFor="coding-changes" className="sr-only">
        Changes to make
      </label>
      <textarea id="coding-changes" className={textareaClass} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. reject nicknames with spaces" />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          busy={busy}
          disabled={changes.length === 0}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              const r = await requestChanges(projectId, detail.summary.task_id, changes);
              setStarted(r.task_id);
              setText("");
              onDone();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Request changes
        </Button>
        {started && <span className="text-xs text-success">Revision started ({started}).</span>}
        {detail.revisions.length > 0 && <span className="text-xs text-muted">{detail.revisions.length} revision(s) so far</span>}
      </div>
      {error ? <InlineError error={error} /> : null}
    </Section>
  );
}
