"use client";

/**
 * Problems that need a person: projects whose run failed (with the failed steps and the reported error) and
 * messages the platform gave up on (dead letters). Only real failure data is shown; the only actions offered are
 * ones the backend supports (open the project, run it again from there). Developer mode shows the raw records.
 */
import Link from "next/link";

import { useWorkspace } from "@/components/AppShell";
import { EmptyState, ErrorState, JsonBlock, LoadingState, Mono, PageHeader, Section, Table, td, th } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { FAILED_TASK_STATES, roleOf, taskStateText } from "@/lib/plain";
import { usePreferences } from "@/lib/preferences";
import type { DeadLetter, Project, Task } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";
import { runOf } from "@/lib/workflow";

function message(err: Record<string, unknown> | null): string | null {
  return err && typeof err.message === "string" ? err.message : null;
}

function FailedProject({ project }: { project: Project }) {
  const { developer } = usePreferences();
  const tasks = useApiQuery(`issue-tasks:${project.project_id}:${project.updated_at}`, (s) => api.listTasks(project.project_id, s));
  const run = project.runs?.at(-1)?.number ?? 1;
  const failed: Task[] = (tasks.data ?? []).filter((t) => runOf(t) === run && (FAILED_TASK_STATES.has(t.state) || t.state === "BLOCKED"));
  const root = failed.filter((t) => t.state !== "BLOCKED");
  const blocked = failed.length - root.length;
  return (
    <li className="hm-clipped rounded-[3px]">
      <span aria-hidden="true" className="hm-clip" />
      <div className="flex items-start gap-4 px-5 pt-5 pb-4 sm:px-7 sm:pt-6">
        <span
          aria-hidden="true"
          className="hm-key hm-key-danger grid size-9 shrink-0 place-items-center rounded-xl bg-danger font-bold text-white dark:text-canvas"
        >
          !
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="pr-16 text-[1.0625rem] font-semibold text-fg">We couldn&apos;t finish “{project.name}”</h3>
          <p className="text-2xs text-muted">Last update {formatRelative(project.updated_at)}</p>
          {tasks.loading ? (
            <p className="mt-2 text-xs text-muted">Loading details…</p>
          ) : (
            <div className="mt-3 space-y-2 text-sm text-fg-2">
              {root.length === 0 && <p>A step could not be completed.</p>}
              {root.map((t) => (
                <p key={t.task_id}>
                  <span className="text-fg">{t.title || t.objective}</span> ({roleOf(t.capability).name}): {taskStateText(t.state).explain}
                  {message(t.last_error) && <span className="block text-xs text-muted">Reported cause: {message(t.last_error)}</span>}
                  {developer && <Mono className="block text-2xs text-muted">{t.task_id}, {t.capability}</Mono>}
                </p>
              ))}
              {blocked > 0 && <p className="text-xs text-muted">{blocked} later step{blocked === 1 ? " was" : "s were"} blocked as a result.</p>}
            </div>
          )}
          {developer && root.map((t) => t.last_error && <JsonBlock key={t.task_id} value={t.last_error} summary={`Error record of ${t.task_id}`} />)}
        </div>
      </div>
      <div className="hm-perforated flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5 sm:px-7">
        <Link
          href={`/projects/${encodeURIComponent(project.project_id)}`}
          className="hm-key hm-key-accent inline-flex h-9 items-center rounded-[5px] bg-accent px-3.5 text-sm font-semibold text-on-accent hover:bg-accent-hover"
        >
          Open the project
        </Link>
        <p className="min-w-0 flex-1 text-xs text-muted">See each step there, then use “Run again”. Change the request first if the input was the problem.</p>
      </div>
    </li>
  );
}

function DeadLetters({ letters, names }: { letters: readonly DeadLetter[]; names: Map<string, string> }) {
  const { developer } = usePreferences();
  if (!developer) {
    return (
      <ul className="hm-tray space-y-3 p-3 sm:p-4">
        {letters.map((d, i) => (
          <li key={i} className="hm-slip rounded-[3px] px-5 py-4 text-sm">
            <div className="flex items-start justify-between gap-3">
              <p className="font-medium">A message could not be delivered after {d.attempts} tries.</p>
              <span className="hm-stamp text-danger">Returned</span>
            </div>
            <p className="text-fg-2">
              {d.project_id ? (
                <>
                  It belonged to{" "}
                  <Link href={`/projects/${encodeURIComponent(d.project_id)}`} className="text-accent-ink hover:underline">
                    {names.get(d.project_id) ?? "one of your projects"}
                  </Link>
                  .{" "}
                </>
              ) : (
                "It was a platform message, not tied to one of your projects. "
              )}
              Reason given: {d.reason}
            </p>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <Table label="Dead-lettered messages" minWidth="48rem">
      <thead>
        <tr>
          <th scope="col" className={th}>Queue</th>
          <th scope="col" className={th}>Reason</th>
          <th scope="col" className={th}>Attempts</th>
          <th scope="col" className={th}>Project</th>
          <th scope="col" className={th}>Payload</th>
        </tr>
      </thead>
      <tbody>
        {letters.map((d, i) => (
          <tr key={i}>
            <td className={td}><Mono>{d.queue}</Mono></td>
            <td className={td}>{d.reason}{d.history.length > 0 && <JsonBlock value={d.history} summary={`History (${d.history.length})`} />}</td>
            <td className={`${td} font-mono text-xs`}>{d.attempts}</td>
            <td className={td}>{d.project_id ? <Mono>{d.project_id}</Mono> : <span className="text-muted">platform</span>}</td>
            <td className={td}>{d.body ? <JsonBlock value={d.body} summary="Raw message" /> : <span className="text-2xs text-muted">hidden (no project)</span>}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export function IssuesView() {
  const { projects, deadLetters } = useWorkspace();
  if (projects.loading || deadLetters.loading) return <LoadingState label="Checking for issues…" />;
  if (projects.error) return <ErrorState error={projects.error} onRetry={projects.reload} />;
  const failed = (projects.data ?? []).filter((p) => p.state === "FAILED");
  const letters = deadLetters.data ?? [];
  const names = new Map((projects.data ?? []).map((p) => [p.project_id, p.name]));
  return (
    <>
      <PageHeader title="Issues" subtitle="Work that could not be completed, what is known about why, and what you can do next." />
      {failed.length === 0 && letters.length === 0 ? (
        <div className="hm-tray">
          <EmptyState title="No open issues">Everything that ran either finished or was stopped on purpose.</EmptyState>
        </div>
      ) : (
        <div className="space-y-12">
          {failed.length > 0 && (
            <Section title={`Projects that couldn't finish (${failed.length})`}>
              <ul className="space-y-8 pt-4">
                {failed.map((p) => (
                  <FailedProject key={p.project_id} project={p} />
                ))}
              </ul>
            </Section>
          )}
          {letters.length > 0 && (
            <Section title={`Undelivered messages (${letters.length})`} description="Messages that failed every retry. Replaying them arrives in a later sprint.">
              <DeadLetters letters={letters} names={names} />
            </Section>
          )}
          {deadLetters.error ? <ErrorState error={deadLetters.error} onRetry={deadLetters.reload} /> : null}
          <p className="text-2xs text-muted">Last checked {formatDateTime(new Date().toISOString())}.</p>
        </div>
      )}
    </>
  );
}
