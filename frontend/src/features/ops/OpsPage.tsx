"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingState,
  Mono,
  PageHeader,
  Section,
  Status,
  Table,
  cx,
  td,
  textareaClass,
  th,
} from "@/components/ui";
import type { FeaturePageProps } from "@/lib/features";
import { formatDateTime, formatRelative } from "@/lib/format";
import { roleOf } from "@/lib/plain";
import { usePreferences } from "@/lib/preferences";
import { useApiQuery } from "@/lib/useApiQuery";

import { explainTask, getDeadLetters, getFailures, getOverview, replayTask } from "./client";
import { VERDICT_LABEL, errorLine, executionLine, reasonProblem, sumValues, taskFromSearch, verdictTone } from "./logic";
import type { Overview, TaskRow } from "./types";

const POLL_MS = 5_000;

/** Page "Operations" (Member 4, Sprint 4 §5b): what needs attention, why a step failed, dead letters and their replay
 * as a new attempt, and links to traces (Jaeger), the dashboard (Grafana) and alerts (Prometheus). */
export function OpsPage(props: FeaturePageProps) {
  void props.route;
  const { developer } = usePreferences();
  const overview = useApiQuery("ops:overview", (signal) => getOverview(signal), { intervalMs: POLL_MS });
  const failures = useApiQuery("ops:failures", (signal) => getFailures(signal), { intervalMs: POLL_MS });
  const dlq = useApiQuery("ops:dlq", (signal) => getDeadLetters(signal), { intervalMs: POLL_MS });
  const [taskId, setTaskId] = useState<string | null>(null);
  const [replaying, setReplaying] = useState<TaskRow | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a deep link (?task=) selects the step once
    setTaskId(taskFromSearch(window.location.search));
  }, []);

  function refresh() {
    overview.reload();
    failures.reload();
    dlq.reload();
  }

  const o = overview.data;
  return (
    <>
      <PageHeader
        title="Operations"
        subtitle="What needs attention in your projects, why a step failed, and what you can do about it."
        actions={
          o && (
            <span className="flex flex-wrap gap-2 text-xs">
              <a className="font-medium text-accent-ink hover:underline" href={o.links.grafana} target="_blank" rel="noreferrer">
                Dashboard (Grafana)
              </a>
              <a className="font-medium text-accent-ink hover:underline" href={o.links.jaeger} target="_blank" rel="noreferrer">
                Traces (Jaeger)
              </a>
              <a className="font-medium text-accent-ink hover:underline" href={`${o.links.prometheus}/alerts`} target="_blank" rel="noreferrer">
                Alerts
              </a>
            </span>
          )
        }
      />
      <div className="flex flex-col gap-8">
        {overview.error ? <ErrorState error={overview.error} onRetry={overview.reload} /> : <OverviewStrip overview={o} developer={developer} />}

        <Section title="Needs attention" description="Steps of your projects that failed, gave up, are blocked or wait for a retry.">
          {failures.loading ? (
            <LoadingState />
          ) : failures.error ? (
            <ErrorState error={failures.error} onRetry={failures.reload} />
          ) : !failures.data?.length ? (
            <EmptyState title="Nothing needs attention">Failed or blocked steps would show up here, with the reason.</EmptyState>
          ) : (
            <ul className="flex flex-col divide-y divide-line/70" aria-label="Steps that need attention">
              {failures.data.map((t) => (
                <li key={t.task_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-fg">{t.title}</span>
                    <span className="block text-xs text-muted">
                      {t.project_name} · {roleOf(t.capability).name} · {formatRelative(t.updated_at)}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <Status tone={t.state === "DEAD_LETTERED" || t.state === "FAILED" ? "danger" : "warning"} label={t.state.toLowerCase().replace(/_/g, " ")} />
                    <Button size="sm" variant={taskId === t.task_id ? "primary" : "secondary"} onClick={() => setTaskId(t.task_id)}>
                      Why?
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        {taskId && <Explain key={taskId} taskId={taskId} developer={developer} onReplay={(row) => setReplaying(row)} onClose={() => setTaskId(null)} />}

        <Section
          title="Dead letters"
          description="Steps that ran out of automatic retries. Nothing is replayed by itself: fix the cause, then replay it as a new attempt."
        >
          {dlq.loading ? (
            <LoadingState />
          ) : dlq.error ? (
            <ErrorState error={dlq.error} onRetry={dlq.reload} />
          ) : !dlq.data?.tasks.length && !dlq.data?.messages.length ? (
            <EmptyState title="No dead letters" />
          ) : (
            <>
              {dlq.data && dlq.data.tasks.length > 0 && (
                <Table label="Dead-lettered steps" minWidth="36rem">
                  <thead>
                    <tr>
                      <th className={th}>Step</th>
                      <th className={th}>Attempts</th>
                      <th className={th}>Last error</th>
                      <th className={cx(th, "relative")}>
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {dlq.data.tasks.map((t) => (
                      <tr key={t.task_id}>
                        <td className={td}>
                          <span className="block text-sm text-fg">{t.title}</span>
                          <span className="block text-xs text-muted">
                            {t.project_name} · {formatRelative(t.updated_at)}
                            {t.replays > 0 && ` · replayed ${t.replays}×`}
                          </span>
                        </td>
                        <td className={cx(td, "tabular-nums")}>{t.attempts}</td>
                        <td className={cx(td, "max-w-[18rem] text-xs text-fg-2")}>{errorLine(t.last_error)}</td>
                        <td className={cx(td, "text-right whitespace-nowrap")}>
                          <Button size="sm" variant="ghost" onClick={() => setTaskId(t.task_id)}>
                            Why?
                          </Button>{" "}
                          <Button size="sm" onClick={() => setReplaying(t)}>
                            Replay…
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
              {dlq.data && dlq.data.messages.length > 0 && (
                <div className="mt-4">
                  <p className="mb-1 text-xs font-medium text-muted">Messages the bus could not deliver ({dlq.data.messages.length})</p>
                  <ul className="flex flex-col gap-1 text-xs">
                    {dlq.data.messages.map((m, i) => (
                      <li key={m.message_id ?? i} className="text-fg-2">
                        <Mono>{m.queue}</Mono> · {m.message_type ?? "message"} · {m.reason}
                        {m.task_id && (
                          <Button size="sm" variant="ghost" onClick={() => setTaskId(m.task_id)}>
                            Why?
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </Section>
      </div>
      <ReplayDialog
        row={replaying}
        onClose={() => setReplaying(null)}
        onDone={(id) => {
          setReplaying(null);
          setTaskId(id);
          refresh();
        }}
      />
    </>
  );
}

function OverviewStrip({ overview, developer }: { overview: Overview | undefined; developer: boolean }) {
  if (!overview) return <LoadingState />;
  const states = overview.tasks_by_state;
  const running = (states.RUNNING ?? 0) + (states.ASSIGNED ?? 0) + (states.ACCEPTED ?? 0);
  const stats = [
    { label: "Dead letters", value: overview.dead_lettered, tone: overview.dead_lettered ? "text-danger" : "text-fg" },
    { label: "Failed", value: states.FAILED ?? 0, tone: states.FAILED ? "text-danger" : "text-fg" },
    { label: "Running now", value: running, tone: "text-fg" },
    { label: "Agents online", value: sumValues(overview.agents_by_state) - (overview.agents_by_state.OFFLINE ?? 0), tone: "text-fg" },
  ];
  return (
    <div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-md border border-line bg-surface px-3 py-2">
            <dt className="text-xs text-muted">{s.label}</dt>
            <dd className={cx("text-xl font-semibold tabular-nums", s.tone)}>{s.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-muted">
        {overview.tracing ? "Tracing is on: each step's trace opens in Jaeger." : "Tracing is off: start it with make obs-up and HMAP_OTEL_ENDPOINT."}
        {developer && Object.keys(overview.queues).length > 0 && (
          <>
            {" "}Queues:{" "}
            {Object.entries(overview.queues)
              .filter(([, n]) => n > 0)
              .map(([q, n]) => `${q} ${n}`)
              .join(", ") || "all empty"}
            .
          </>
        )}
      </p>
    </div>
  );
}

function Explain({ taskId, developer, onReplay, onClose }: { taskId: string; developer: boolean; onReplay: (row: TaskRow) => void; onClose: () => void }) {
  const q = useApiQuery(`ops:explain:${taskId}`, (signal) => explainTask(taskId, signal), { intervalMs: POLL_MS });
  if (q.loading) return <LoadingState label="Working out what happened…" />;
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  const x = q.data;
  if (!x) return null;
  const v = x.verdict;
  const row: TaskRow = {
    task_id: x.task.task_id, project_id: x.task.project_id, project_name: null, capability: x.task.capability,
    title: x.task.title ?? x.task.objective, state: x.task.state, attempts: x.task.attempts, replays: x.task.replays,
    last_error: x.task.last_error as TaskRow["last_error"], updated_at: x.task.updated_at, plan_task_id: x.task.plan_task_id,
  };
  return (
    <Section
      title={`Why: ${x.task.title ?? x.task.objective}`}
      description={`${roleOf(x.task.capability).name} · ${x.executions.length} attempt${x.executions.length === 1 ? "" : "s"}`}
      actions={
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className={cx("border-l-2 px-3 py-2", verdictTone(v.status) === "danger" ? "border-danger bg-danger-soft" : verdictTone(v.status) === "success" ? "border-success bg-success-soft" : "border-warning bg-warning-soft")}>
        <Status tone={verdictTone(v.status)} label={VERDICT_LABEL[v.status] ?? v.status} />
        <p className="mt-1 text-sm text-fg">{v.headline}</p>
        {v.facts.length > 0 && (
          <ul className="mt-1 list-disc pl-5 text-xs text-fg-2">
            {v.facts.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        )}
        <div className="mt-2 flex flex-wrap gap-2">
          {v.actions.find((a) => a.action === "replay" && a.allowed) && (
            <Button size="sm" variant="primary" onClick={() => onReplay(row)}>
              Replay as a new attempt…
            </Button>
          )}
          {v.actions.find((a) => a.action === "replan" && a.allowed) && (
            <Link className="text-xs font-medium text-accent-ink hover:underline" href={`/projects/${encodeURIComponent(x.task.project_id)}`}>
              Open the project to change the plan
            </Link>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-medium text-muted">Attempts</h3>
          <ol className="flex flex-col gap-1.5 text-xs">
            {x.executions.map((e) => (
              <li key={e.execution_id} className="rounded border border-line/70 px-2 py-1.5">
                <span className="text-fg">{executionLine(e)}</span>
                {e.error?.message && <span className="block text-fg-2">{e.error.message}</span>}
                {e.late_reports.length > 0 && (
                  <span className="block text-muted">
                    {e.late_reports.length} late report{e.late_reports.length === 1 ? "" : "s"} kept as evidence ({e.late_reports.map((r) => r.message_type).join(", ")})
                  </span>
                )}
                {developer && <Mono className="block text-2xs">{e.execution_id}</Mono>}
              </li>
            ))}
            {!x.executions.length && <li className="text-muted">No attempt yet.</li>}
          </ol>
          {x.dependants.length > 0 && (
            <>
              <h3 className="mt-3 mb-1 text-xs font-medium text-muted">Steps that wait for it</h3>
              <ul className="text-xs text-fg-2">
                {x.dependants.map((d) => (
                  <li key={d.task_id}>
                    {d.title ?? d.task_id} — {d.state.toLowerCase().replace(/_/g, " ")}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div>
          <h3 className="mb-1 text-xs font-medium text-muted">What happened, in order</h3>
          <ol className="max-h-72 overflow-auto text-xs">
            {x.timeline.map((e, i) => (
              <li key={`${e.seq ?? i}`} className="flex gap-2 border-b border-line/50 py-1">
                <span className="shrink-0 text-muted tabular-nums">{e.at ? formatDateTime(e.at).split(", ").at(-1) : ""}</span>
                <span className="text-fg-2">{e.summary}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-2 text-xs">
        <p>
          <span className="font-medium text-muted">Messages: </span>
          {x.messages.length
            ? x.messages.map((m) => `${m.published_at ? "sent" : "waiting in the outbox"}${m.processed_by.length ? ", processed once" : ""}`).join("; ")
            : "none"}
          {developer && x.messages.map((m) => <Mono key={m.message_id} className="ml-2 text-2xs">{m.message_id}</Mono>)}
        </p>
        <p>
          <span className="font-medium text-muted">Trace: </span>
          {x.trace.links.map((l, i) => (
            <a key={l} href={l} target="_blank" rel="noreferrer" className="mr-2 text-accent-ink hover:underline">
              {x.trace.links.length > 1 ? `trace ${i + 1}` : "open in Jaeger"}
            </a>
          ))}
          {!x.trace.tracing && <span className="text-muted">(tracing was off; the link works once traces are sent)</span>}
        </p>
        {x.artifacts.length > 0 && (
          <p>
            <span className="font-medium text-muted">Results: </span>
            {x.artifacts.map((a) => (
              <Badge key={`${a.artifact_id}:${a.version}`} className="mr-1">
                {a.artifact_type} v{a.version}
              </Badge>
            ))}
          </p>
        )}
      </div>
    </Section>
  );
}

function ReplayDialog({ row, onClose, onDone }: { row: TaskRow | null; onClose: () => void; onDone: (taskId: string) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const problem = reasonProblem(reason);

  async function submit() {
    if (!row || problem) return;
    setBusy(true);
    setError(null);
    try {
      await replayTask(row.task_id, reason.trim());
      setReason("");
      onDone(row.task_id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={row !== null}
      onClose={onClose}
      title="Replay as a new attempt?"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} disabled={Boolean(problem)} onClick={() => void submit()}>
            Replay
          </Button>
        </>
      }
    >
      {row && (
        <>
          <p>
            “{row.title}” gave up after {row.attempts} attempt{row.attempts === 1 ? "" : "s"} ({errorLine(row.last_error)}). Replaying starts a{" "}
            <strong>new attempt</strong> with a fresh retry budget; the failed attempts stay in the history, and the steps that wait for it
            continue if it succeeds.
          </p>
          <label htmlFor="replay-reason" className="mt-3 block text-sm font-medium text-fg">
            Why is it safe to try again?
          </label>
          <textarea
            id="replay-reason"
            className={cx(textareaClass, "mt-1 min-h-20")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. the source website is back online"
            maxLength={500}
            aria-invalid={Boolean(reason) && Boolean(problem)}
          />
          {reason && problem && <p className="mt-1 text-xs text-danger">{problem}</p>}
          <InlineError error={error} />
        </>
      )}
    </Dialog>
  );
}
