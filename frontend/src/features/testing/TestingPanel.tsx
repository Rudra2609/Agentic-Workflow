"use client";

import { useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  Mono,
  Section,
  Spinner,
  Status,
  cx,
} from "@/components/ui";
import type { ProjectPanelProps } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

import {
  getQuarantine,
  getRun,
  listRuns,
  logUrl,
  releaseTest,
  rerun,
} from "./client";
import {
  BACKEND_TEXT,
  CATEGORY_TEXT,
  STAGE_TEXT,
  STATUS_TONE,
  percent,
  roundTitle,
  sortFailures,
  stagesInOrder,
  testingEventKey,
  where,
} from "./logic";
import type {
  Failure,
  RunDetail,
  RunSummary,
  StepRecord,
  TestingTrace,
} from "./types";

/** Project tab "Testing" (Member 8): each test run's stage timeline, failures with hints, logs, the test -> fix ->
 * re-test loop, and a "Re-run" button. */
export function TestingPanel({ projectId, events, reload }: ProjectPanelProps) {
  const runs = useApiQuery(
    `testing:${projectId}:${testingEventKey(events)}`,
    (signal) => listRuns(projectId, signal),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const list = runs.data ?? [];
  const current = list.find((r) => r.task_id === selected) ?? list[0];

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Testing"
        description="The testing agent runs each coding step's code in a locked-down sandbox: static checks, build, unit and integration tests, security checks. Real failures go back to the coding agent, which fixes them, and the code is tested again."
      >
        {runs.loading ? (
          <LoadingState label="Loading the test runs…" />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={runs.reload} />
        ) : list.length === 0 ? (
          <EmptyState title="No test runs yet">
            Each implementation step of the plan is tested once its code is
            written.
          </EmptyState>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Test runs">
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
      <QuarantineList
        projectId={projectId}
        refreshKey={testingEventKey(events)}
      />
      {current && (
        <Detail
          key={`${current.task_id}:${current.status}:${current.failures}`}
          projectId={projectId}
          summary={current}
          onRerun={() => {
            runs.reload();
            reload();
          }}
        />
      )}
    </div>
  );
}

function Verdict({ run }: { run: Pick<RunSummary, "status" | "passed"> }) {
  if (run.status === "running")
    return <Spinner className="size-3 shrink-0" label="testing" />;
  return (
    <Status
      tone={run.passed ? "success" : "danger"}
      label={run.passed ? "passed" : "failed"}
    />
  );
}

function RunCard({
  run,
  active,
  onSelect,
}: {
  run: RunSummary;
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
          {roundTitle(run.loop_round)}
        </span>
        <Verdict run={run} />
      </span>
      <span className="line-clamp-2 text-xs text-fg-2">{run.objective}</span>
      <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
        <span>
          {run.tests - run.tests_failed}/{run.tests} tests passed
        </span>
        {run.failures > 0 && (
          <span className="text-danger">{run.failures} failure(s)</span>
        )}
        {run.lint > 0 && <span>{run.lint} lint</span>}
        {run.flaky > 0 && (
          <span className="text-warning">{run.flaky} flaky</span>
        )}
        {run.coverage !== null && <span>coverage {run.coverage}%</span>}
        <span>{run.backend}</span>
      </span>
    </button>
  );
}

function Detail({
  projectId,
  summary,
  onRerun,
}: {
  projectId: string;
  summary: RunSummary;
  onRerun: () => void;
}) {
  const run = useApiQuery(
    `testing:run:${projectId}:${summary.task_id}:${summary.status}:${summary.failures}`,
    (signal) => getRun(projectId, summary.task_id, signal),
  );
  if (run.loading) return <LoadingState label="Loading the test run…" />;
  if (run.error) return <ErrorState error={run.error} onRetry={run.reload} />;
  const d = run.data;
  if (!d) return null;
  const t = d.trace;
  return (
    <div className="flex flex-col gap-6">
      <Section
        title={roundTitle(t.loop.round)}
        description={`${BACKEND_TEXT[t.backend] ?? t.backend} · tested ${t.files} files from ${t.workspace_from || "—"} · updated ${formatDateTime(d.summary.updated_at)}`}
        actions={
          d.summary.status === "done" ? (
            <a
              className="text-xs text-accent underline"
              href={logUrl(projectId, d.summary.task_id)}
              target="_blank"
              rel="noreferrer"
            >
              Full log
            </a>
          ) : null
        }
      >
        <p className="text-sm text-fg">{t.objective}</p>
        {t.acceptance_criteria.length > 0 && (
          <ul
            className="mt-2 list-disc pl-5 text-xs text-fg-2"
            aria-label="Acceptance criteria"
          >
            {t.acceptance_criteria.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}
        <Timeline detail={d} />
        {t.notes.length > 0 && (
          <ul className="mt-2 text-xs text-muted" aria-label="Notes">
            {t.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </Section>
      {d.loop.length > 1 && <Loop rows={d.loop} current={t.task_id} />}
      <Extras trace={t} />
      <Section
        title="Failures"
        description={
          t.failures.length
            ? "What failed, where, and a hint for the fix. Lint and flaky tests are shown but do not fail the run."
            : "Nothing failed."
        }
      >
        <Failures failures={sortFailures(t.failures)} />
      </Section>
      {d.generated_tests && (
        <Section
          title="Generated tests"
          description={`The code had no tests, so tests were written from the acceptance criteria. ${t.generated.kept?.length ?? 0} kept, ${Object.keys(t.generated.dropped ?? {}).length} dropped by the check that a test must fail on code that does nothing.`}
        >
          <pre
            className="max-h-72 overflow-auto rounded bg-surface-2 p-2 text-[11px] leading-snug whitespace-pre-wrap"
            aria-label="Generated test file"
          >
            {d.generated_tests}
          </pre>
        </Section>
      )}
      <Section
        title="Commands"
        description="Every command the sandbox ran, with its output."
      >
        <Steps steps={t.steps} running={t.status === "running"} />
      </Section>
      {d.summary.status === "done" && (
        <Rerun
          projectId={projectId}
          taskId={d.summary.task_id}
          onDone={onRerun}
        />
      )}
    </div>
  );
}

function Timeline({ detail }: { detail: RunDetail }) {
  return (
    <ol className="mt-3 flex flex-wrap gap-2" aria-label="Stages">
      {stagesInOrder(detail.trace).map((s) => (
        <li
          key={s.name}
          className="flex flex-col gap-0.5 rounded border border-line px-2.5 py-1.5 text-xs"
          title={STAGE_TEXT[s.name]?.help}
        >
          <span className="flex items-center gap-2">
            <span className="font-medium text-fg">
              {STAGE_TEXT[s.name]?.label ?? s.name}
            </span>
            <Status tone={STATUS_TONE[s.status]} label={s.status} />
          </span>
          <span className="text-muted">
            {s.tests ? `${s.tests - s.tests_failed}/${s.tests} tests · ` : ""}
            {s.duration_s ? `${s.duration_s.toFixed(1)} s` : s.detail || "—"}
          </span>
        </li>
      ))}
      {detail.trace.coverage !== null && (
        <li className="self-center text-xs text-fg-2">
          coverage <strong>{detail.trace.coverage}%</strong>
        </li>
      )}
    </ol>
  );
}

function Loop({ rows, current }: { rows: RunSummary[]; current: string }) {
  return (
    <Section
      title="Test → fix → re-test"
      description="Failed tests went back to the coding agent; each row is one round (it stops when the tests pass, after the round limit, or when a fix does not help)."
    >
      <ol className="flex flex-col gap-1.5" aria-label="Loop rounds">
        {rows.map((r) => (
          <li
            key={r.task_id}
            className={cx(
              "flex flex-wrap items-center gap-3 rounded border px-2.5 py-1.5 text-xs",
              r.task_id === current ? "border-accent" : "border-line",
            )}
          >
            <span className="font-medium text-fg">
              {roundTitle(r.loop_round)}
            </span>
            <Verdict run={r} />
            <span className="text-fg-2">
              {r.tests - r.tests_failed}/{r.tests} tests (
              {percent(r.pass_ratio)})
            </span>
            {r.failures > 0 && (
              <span className="text-danger">{r.failures} failure(s)</span>
            )}
          </li>
        ))}
      </ol>
    </Section>
  );
}

function Failures({ failures }: { failures: Failure[] }) {
  if (failures.length === 0)
    return <p className="text-xs text-success">All stages passed.</p>;
  return (
    <ul className="flex flex-col gap-2" aria-label="Failure list">
      {failures.map((f, i) => (
        <li
          key={i}
          className={cx(
            "rounded border px-2.5 py-2 text-xs",
            f.category === "LINT" || f.flaky
              ? "border-line"
              : "border-danger/50",
          )}
        >
          <span className="flex flex-wrap items-baseline gap-2">
            <Badge>{CATEGORY_TEXT[f.category]}</Badge>
            <Mono>{where(f)}</Mono>
            <span className="text-muted">{f.stage}</span>
            {f.generated && (
              <Badge title="from a test written by the testing agent; never sent for a fix on its own">
                generated test
              </Badge>
            )}
            {f.flaky && (
              <Badge title="failed once, passed when run again">flaky</Badge>
            )}
            {f.fuzz && (
              <Badge title="found by fuzzing; shown, not counted, never sent for a fix on its own">
                fuzz
              </Badge>
            )}
          </span>
          <p className="mt-1 break-words text-fg-2">{f.message}</p>
          {f.hint && (
            <p className="mt-1 text-fg">
              <span className="text-muted">
                {f.hint_by === "model" ? "Hint (AI): " : "Hint: "}
              </span>
              {f.hint}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function Steps({ steps, running }: { steps: StepRecord[]; running: boolean }) {
  if (steps.length === 0)
    return (
      <p className="text-xs text-muted">
        {running ? "Starting…" : "Nothing ran."}
      </p>
    );
  return (
    <ol className="flex flex-col gap-1.5" aria-label="Command log">
      {steps.map((s, i) => {
        const ok = !s.timed_out && s.exit_code === 0;
        return (
          <li
            key={i}
            className="rounded border border-line/70 px-2.5 py-1.5 text-xs"
          >
            <details>
              <summary className="flex cursor-pointer flex-wrap items-baseline gap-2">
                <Badge>{s.stage}</Badge>
                <Mono>{s.cmd || s.name}</Mono>
                <span className={ok ? "text-success" : "text-danger"}>
                  {s.timed_out ? "timed out" : `exit ${s.exit_code ?? "?"}`}
                </span>
                <span className="text-muted">{s.duration_s.toFixed(1)} s</span>
              </summary>
              <pre className="mt-1.5 max-h-72 overflow-auto rounded bg-surface-2 p-2 text-[11px] leading-snug whitespace-pre-wrap">
                {s.output || "(no output)"}
              </pre>
            </details>
          </li>
        );
      })}
      {running && (
        <li className="text-xs text-muted">
          <Spinner className="size-3" label="working" /> working…
        </li>
      )}
    </ol>
  );
}

function Rerun({
  projectId,
  taskId,
  onDone,
}: {
  projectId: string;
  taskId: string;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [started, setStarted] = useState<string | null>(null);
  return (
    <Section
      title="Re-run"
      description="Run the same tests again on the same code (for example after starting Docker)."
    >
      <div className="flex flex-wrap items-center gap-3">
        <Button
          busy={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              const r = await rerun(projectId, taskId);
              setStarted(r.task_id);
              onDone();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Re-run the tests
        </Button>
        {started && (
          <span className="text-xs text-success">
            Re-run started ({started}).
          </span>
        )}
      </div>
      {error ? <InlineError error={error} /> : null}
    </Section>
  );
}

function QuarantineList({
  projectId,
  refreshKey,
}: {
  projectId: string;
  refreshKey: string;
}) {
  const q = useApiQuery(
    `testing:quarantine:${projectId}:${refreshKey}`,
    (signal) => getQuarantine(projectId, signal),
  );
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const tests = Object.entries(q.data?.tests ?? {});
  if (q.loading || q.error || tests.length === 0) return null;
  return (
    <Section
      title="Quarantined flaky tests"
      description={`These tests failed once and passed when run again. They still run, but their failures do not count and are never sent for a fix; each is released after ${q.data?.release_after ?? 3} clean passes in a row.`}
    >
      <ul className="flex flex-col gap-1.5" aria-label="Quarantined tests">
        {tests.map(([node, e]) => (
          <li
            key={node}
            className="flex flex-wrap items-center gap-3 rounded border border-line px-2.5 py-1.5 text-xs"
          >
            <Mono>{node}</Mono>
            <span className="text-muted">
              flaky {e.flaky}× · {e.clean_passes} clean pass(es) since
            </span>
            <Button
              busy={busy === node}
              onClick={async () => {
                setBusy(node);
                setError(null);
                try {
                  await releaseTest(projectId, node);
                  q.reload();
                } catch (err) {
                  setError(err);
                } finally {
                  setBusy(null);
                }
              }}
            >
              Release
            </Button>
          </li>
        ))}
      </ul>
      {error ? <InlineError error={error} /> : null}
    </Section>
  );
}

function Extras({ trace: t }: { trace: TestingTrace }) {
  const m = t.mutation;
  const z = t.fuzz;
  const dep = t.dependencies;
  if (
    !m &&
    !z &&
    !(dep && (dep.audited.length || dep.unpinned.length)) &&
    (t.language ?? "python") === "python"
  )
    return null;
  return (
    <Section
      title="Extra checks"
      description="Quality checks beyond pass / fail: how many planted faults the tests catch, what fuzzing found, and known-vulnerable dependencies."
    >
      <ul className="flex flex-col gap-2 text-xs" aria-label="Extra checks">
        {t.language && t.language !== "python" && (
          <li>
            <Badge>JS/TS</Badge>{" "}
            <span className="text-fg-2">
              tested in the Node sandbox image (ESLint, tsc, node --test)
            </span>
          </li>
        )}
        {m && (
          <li>
            <span className="font-medium text-fg">Mutation score: </span>
            {m.error ? (
              <span className="text-muted">{m.error}</span>
            ) : (
              <span>
                {m.killed}/{m.total} planted faults caught ({percent(m.score)})
                {m.survived.length > 0 && (
                  <span className="text-warning">
                    {" "}
                    · not caught:{" "}
                    {m.survived
                      .slice(0, 5)
                      .map((s) => `${s.file}:${s.line} (${s.op})`)
                      .join(", ")}
                  </span>
                )}
              </span>
            )}
          </li>
        )}
        {z && (
          <li>
            <span className="font-medium text-fg">Fuzzing: </span>
            {z.note || z.error ? (
              <span className="text-muted">{z.note || z.error}</span>
            ) : (
              <span>
                {z.targets} function(s), {z.findings ?? 0} finding(s)
              </span>
            )}
          </li>
        )}
        {dep && (dep.audited.length > 0 || dep.unpinned.length > 0) && (
          <li>
            <span className="font-medium text-fg">Dependencies: </span>
            <span>
              {dep.audited.length} pinned audited ({dep.source})
              {dep.vulnerable.length > 0 && (
                <span className="text-danger">
                  {" "}
                  · {dep.vulnerable.length} known vulnerabilit
                  {dep.vulnerable.length === 1 ? "y" : "ies"}
                </span>
              )}
              {dep.unpinned.length > 0 && (
                <span className="text-muted">
                  {" "}
                  · {dep.unpinned.length} unpinned (not audited)
                </span>
              )}
              {dep.note && <span className="text-muted"> · {dep.note}</span>}
            </span>
          </li>
        )}
      </ul>
    </Section>
  );
}
