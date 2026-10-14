"use client";

/**
 * Details of one step (task). Simple mode: what it is, who does it, its state in words, what "done" means, its
 * files and any problem. Developer mode adds ids, capability, agent, inputs, attempts, executions and events.
 * Nothing is estimated: no progress percentage is shown unless the agent reported one.
 */
import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api";
import { formatBytes, formatDateTime, formatDuration, formatTime, shortId } from "@/lib/format";
import { roleOf, taskStateText } from "@/lib/plain";
import { usePreferences } from "@/lib/preferences";
import { TERMINAL_TASK_STATES, type ArtifactRef, type Execution, type HmapEvent } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";
import { useEventTrigger } from "@/lib/useEventStream";

import { ExecutionStatusChip } from "./StateChip";
import { Badge, Button, ErrorState, InlineError, JsonBlock, LoadingState, Mono, Status, cx } from "./ui";

export function FileLinks({ projectId, refs }: { projectId: string; refs: readonly ArtifactRef[] }) {
  if (refs.length === 0) return <p className="text-sm text-muted">No files yet.</p>;
  return (
    <ul className="space-y-1">
      {refs.map((r) => (
        <li key={`${r.artifact_id}@${r.version}`} className="flex flex-wrap items-center gap-x-2 text-sm">
          <a
            href={api.artifactUrl(projectId, r.artifact_id, r.version)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-ink underline-offset-2 hover:underline"
          >
            {r.artifact_type.replace(/[-_]/g, " ")}
          </a>
          <span className="text-2xs text-muted">
            {r.media_type} · {formatBytes(r.size_bytes)}
          </span>
          <a href={api.artifactUrl(projectId, r.artifact_id, r.version, true)} className="text-2xs text-muted hover:text-fg">
            Download
          </a>
        </li>
      ))}
    </ul>
  );
}

function errorText(error: Record<string, unknown> | null | undefined): string | null {
  if (!error) return null;
  return typeof error.message === "string" ? error.message : null;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)] gap-2 py-1 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function ExecutionRow({ exe }: { exe: Execution }) {
  const ms = Date.parse(exe.updated_at) - Date.parse(exe.created_at);
  return (
    <li className="border-t border-line py-2 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium">Attempt {exe.attempt}</span>
        <ExecutionStatusChip status={exe.status} />
        <Mono className="ml-auto text-muted" title={exe.execution_id}>
          {shortId(exe.execution_id, 12)}
        </Mono>
      </div>
      <dl className="mt-1 text-xs">
        <Row label="Agent">{exe.agent_id ? <Mono title={exe.agent_id}>{exe.agent_id}</Mono> : "—"}</Row>
        <Row label="Started">{formatDateTime(exe.created_at)}</Row>
        <Row label="Duration">{Number.isFinite(ms) ? formatDuration(ms) : "—"}</Row>
        {exe.lease_until && <Row label="Lease until">{formatDateTime(exe.lease_until)}</Row>}
      </dl>
      {exe.error && <JsonBlock value={exe.error} summary="Error details" />}
      {exe.evidence.length > 0 && <JsonBlock value={exe.evidence} summary={`Late reports kept as evidence (${exe.evidence.length})`} />}
    </li>
  );
}

export function TaskInspector({
  projectId,
  taskId,
  events,
  stubCapabilities,
  onClose,
  onChanged,
}: {
  projectId: string;
  taskId: string;
  events: readonly HmapEvent[];
  stubCapabilities: ReadonlySet<string>;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { developer } = usePreferences();
  const task = useApiQuery(`task:${taskId}`, (s) => api.getTask(taskId, s));
  useEventTrigger(events, (e) => e.aggregate_id === taskId, task.reload);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await api.cancelTask(taskId);
      setConfirm(false);
      task.reload();
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const t = task.data;
  const st = t ? taskStateText(t.state) : null;
  const role = t ? roleOf(t.capability) : null;
  const exes = t?.executions ?? [];
  const files = exes.flatMap((e) => e.result_refs);
  const problem = t ? errorText(t.last_error) ?? errorText(exes.at(-1)?.error) : null;
  const progress = events.filter((e) => e.aggregate_id === taskId && e.event_type === "task.progress").at(-1);
  const percent = typeof progress?.data.percent === "number" ? progress.data.percent : null;
  const progressMsg = typeof progress?.data.message === "string" ? progress.data.message : null;
  const myEvents = events.filter((e) => e.aggregate_id === taskId);

  return (
    <aside aria-label="Step details" className="hm-clipped rounded-[3px]">
      <span aria-hidden="true" className="hm-clip" />
      <header className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight">{t ? t.title || t.objective : "Loading…"}</h2>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close step details">
          Close
        </Button>
      </header>
      <div className="space-y-4 px-4 py-3">
        {task.loading ? (
          <LoadingState />
        ) : task.error ? (
          <ErrorState error={task.error} onRetry={task.reload} />
        ) : t && st && role ? (
          <>
            <div>
              <Status tone={st.tone} label={st.label} live={st.tone === "progress"} />
              <p className="mt-1 text-sm text-fg-2">{st.explain}</p>
              {percent !== null && t.state === "RUNNING" && (
                <p className="mt-1 text-xs text-muted">
                  Reported progress: {percent}%{progressMsg ? ` — ${progressMsg}` : ""}
                </p>
              )}
            </div>
            <dl>
              <Row label="Done by">
                {role.name}
                {stubCapabilities.has(t.capability) && <Badge className="ml-2 bg-warning-soft text-warning">placeholder</Badge>}
                <span className="block text-xs text-muted">{role.does}</span>
              </Row>
              {t.title && t.objective !== t.title && <Row label="What">{t.objective}</Row>}
              {t.acceptance_criteria.length > 0 && (
                <Row label="Done when">
                  <ul className="list-disc pl-4">
                    {t.acceptance_criteria.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </Row>
              )}
              {t.depends_on.length > 0 && <Row label="After">{t.depends_on.length} earlier step(s)</Row>}
            </dl>
            {problem && (
              <div className="border-l-2 border-danger bg-danger-soft px-3 py-2 text-sm">
                <p className="font-medium">What went wrong</p>
                <p className="mt-0.5 text-fg-2">{problem}</p>
                <Link href={`/features/ops?task=${encodeURIComponent(taskId)}`} className="mt-1 inline-block text-xs font-medium text-accent-ink hover:underline">
                  Why did this step fail?
                </Link>
              </div>
            )}
            <div>
              <h3 className="mb-1 text-xs font-medium text-muted">Result files</h3>
              <FileLinks projectId={projectId} refs={files} />
              {files.length > 0 && stubCapabilities.has(t.capability) && (
                <p className="mt-1 text-2xs text-muted">Produced by a placeholder agent: sample content, not real work.</p>
              )}
            </div>
            {!TERMINAL_TASK_STATES.has(t.state) && (
              <div className="flex flex-wrap items-center gap-2">
                {confirm ? (
                  <>
                    <Button size="sm" variant="danger" busy={busy} onClick={cancel}>
                      Stop this step
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirm(false)} disabled={busy}>
                      Keep it
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="quiet-danger" onClick={() => setConfirm(true)}>
                    Stop this step…
                  </Button>
                )}
                <InlineError error={error} />
              </div>
            )}

            {developer && (
              <div className="space-y-3 border-t border-line pt-3">
                <h3 className="text-sm font-medium text-fg">Technical details</h3>
                <dl className="text-xs">
                  <Row label="Task ID"><Mono>{t.task_id}</Mono></Row>
                  <Row label="Capability"><Mono>{t.capability}</Mono></Row>
                  <Row label="State"><Mono>{t.state}</Mono> · v{t.state_version}</Row>
                  <Row label="Run">{t.run ?? 1}{t.plan_task_id ? ` · plan step ${t.plan_task_id}` : ""}</Row>
                  <Row label="Attempts">{t.attempts} (retries {t.retries}, rejections {t.rejections})</Row>
                  <Row label="Created">{formatDateTime(t.created_at)}</Row>
                  <Row label="Updated">{formatDateTime(t.updated_at)}</Row>
                  {t.retry_at && <Row label="Retry at">{formatDateTime(t.retry_at)}</Row>}
                  {t.blocked_by.length > 0 && <Row label="Blocked by"><Mono>{t.blocked_by.join(", ")}</Mono></Row>}
                </dl>
                {Object.keys(t.inputs).length > 0 && <JsonBlock value={t.inputs} summary="Inputs" />}
                {t.last_error && <JsonBlock value={t.last_error} summary="Last error" />}
                <div>
                  <p className="mb-1 text-xs font-medium text-muted">Executions</p>
                  {exes.length ? <ul>{exes.map((e) => <ExecutionRow key={e.execution_id} exe={e} />)}</ul> : <p className="text-xs text-muted">None yet.</p>}
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium text-muted">Events ({myEvents.length})</p>
                  <ul className="max-h-48 overflow-auto font-mono text-2xs">
                    {myEvents.map((e) => (
                      <li key={e.seq} className="flex gap-2 py-0.5">
                        <span className="text-muted">#{e.seq}</span>
                        <span className="text-muted">{formatTime(e.occurred_at)}</span>
                        <span className={cx(/failed|dead/.test(e.event_type) && "text-danger")}>{e.event_type}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <JsonBlock value={t} summary="Raw task record" />
              </div>
            )}
          </>
        ) : null}
      </div>
    </aside>
  );
}
