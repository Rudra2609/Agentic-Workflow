"use client";

/**
 * The project workspace. Everything shown comes from the API for this project (owner-checked server-side):
 * runs, tasks, approvals, files and events. Simple mode explains; developer mode adds ids, raw events and records.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState, type FormEvent } from "react";

import { ActivityTimeline, timelineEntries } from "@/components/ActivityTimeline";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { EventLog } from "@/components/EventLog";
import { Tabs, type TabItem } from "@/components/Tabs";
import { FileLinks, TaskInspector } from "@/components/TaskInspector";
import { useToast } from "@/components/Toast";
import { PlanGraph, StageRail } from "@/components/Workflow";
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  InlineError,
  LoadingState,
  Mono,
  Section,
  Status,
  cx,
  inputClass,
  textareaClass,
} from "@/components/ui";
import { api, isApiError } from "@/lib/api";
import { PROJECT_PANELS } from "@/lib/featureRegistry";
import { formatBytes, formatDateTime, formatRelative } from "@/lib/format";
import { ACTIVE_PROJECT_STATES, projectStateText, roleOf } from "@/lib/plain";
import { usePreferences } from "@/lib/preferences";
import type { ArtifactItem, Project, Task } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";
import { useEventStream, useEventTrigger } from "@/lib/useEventStream";
import { approvalsOfRun, currentRun, documentsSummary, runOf, stagesOf } from "@/lib/workflow";

const FINISHED: ReadonlySet<string> = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

// ------------------------------------------------------------------ Stop button (two-step)

/** The human's emergency brake: cancels every unfinished step and closes the run (two-step confirm). */
export function StopProjectButton({ projectId, onStopped }: { projectId: string; onStopped: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      await api.stopProject(projectId);
      setConfirming(false);
      onStopped();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {confirming ? (
        <>
          <span className="text-sm font-medium text-danger">Stop all work on this project?</span>
          <Button variant="danger" busy={busy} onClick={stop}>
            Yes, stop now
          </Button>
          <Button variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>
            Keep running
          </Button>
        </>
      ) : (
        <Button variant="danger" onClick={() => setConfirming(true)} aria-label="Stop project">
          <span aria-hidden="true">■</span> Stop
        </Button>
      )}
      <InlineError error={error} />
    </span>
  );
}

// ------------------------------------------------------------------ header actions

function RunAgainDialog({ project, open, onClose, onStarted }: { project: Project; open: boolean; onClose: () => void; onStarted: () => void }) {
  const last = project.runs?.at(-1)?.goal ?? project.description ?? "";
  const [goal, setGoal] = useState(last);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const id = useId();
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (goal.trim().length < 10) {
      setError(new Error("Describe the goal in at least 10 characters."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.startRun(project.project_id, goal);
      onStarted();
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Run this project again"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} type="submit" form={`${id}-form`}>
            Start new run
          </Button>
        </>
      }
    >
      <form id={`${id}-form`} onSubmit={submit} className="space-y-3">
        <p>Earlier runs and their results stay in the history. Change the request if you want a different outcome.</p>
        <Field label="Request" htmlFor={id}>
          {() => <textarea id={id} className={textareaClass} value={goal} onChange={(e) => setGoal(e.target.value)} rows={5} maxLength={20000} />}
        </Field>
        <p className="text-xs text-muted">
          {project.auto_approve ? "This project runs automatically: the new plan starts without a review." : "You'll review the new plan before work starts."}
        </p>
        <InlineError error={error} />
      </form>
    </Dialog>
  );
}

function MoreMenu({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [name, setName] = useState(project.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const nameId = useId();

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <details className="relative">
        <summary className="inline-flex h-9 cursor-pointer list-none items-center rounded-md border border-line-strong bg-surface px-3 text-sm hover:bg-hover">
          More
        </summary>
        <div className="absolute right-0 z-20 mt-1 w-48 rounded-md border border-line bg-surface p-1 shadow-xl">
          <button type="button" className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-hover" onClick={() => setRenaming(true)}>
            Rename
          </button>
          <button
            type="button"
            className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-hover"
            onClick={() =>
              void run(async () => {
                await api.updateProject(project.project_id, { archived: !project.archived });
                toast(project.archived ? "Project restored to your workspace." : "Project archived.");
                onChanged();
              })
            }
          >
            {project.archived ? "Restore from archive" : "Archive"}
          </button>
          <button
            type="button"
            className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-hover"
            onClick={() =>
              void run(async () => {
                const local = project.cloud_ok !== false;
                await api.updateProject(project.project_id, { cloud_ok: !local });
                toast(local ? "This project now stays on this computer. Steps already running keep their model." : "Cloud models are allowed for this project's next steps.");
                onChanged();
              })
            }
          >
            {project.cloud_ok === false ? "Allow cloud models" : "Keep on this computer"}
          </button>
          <button type="button" className="block w-full rounded px-2 py-1.5 text-left text-sm text-danger hover:bg-danger-soft" onClick={() => setDeleting(true)}>
            Delete…
          </button>
        </div>
      </details>
      <Dialog
        open={renaming}
        onClose={() => setRenaming(false)}
        title="Rename project"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRenaming(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              busy={busy}
              disabled={!name.trim()}
              onClick={() =>
                void run(async () => {
                  await api.updateProject(project.project_id, { name: name.trim() });
                  setRenaming(false);
                  toast("Project renamed.");
                  onChanged();
                })
              }
            >
              Save
            </Button>
          </>
        }
      >
        <Field label="Name" htmlFor={nameId}>
          {() => <input id={nameId} className={inputClass} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <InlineError error={error} />
      </Dialog>
      <Dialog
        open={deleting}
        onClose={() => setDeleting(false)}
        title={`Delete “${project.name}”?`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(false)}>
              Keep project
            </Button>
            <Button
              variant="danger"
              busy={busy}
              onClick={() =>
                void run(async () => {
                  const r = await api.deleteProject(project.project_id);
                  toast(`Project deleted (${r.files_erased} file${r.files_erased === 1 ? "" : "s"} erased).`);
                  router.push("/");
                })
              }
            >
              Delete permanently
            </Button>
          </>
        }
      >
        <ul className="list-disc space-y-1 pl-5">
          <li>Any work still running is stopped first.</li>
          <li>All of the project&apos;s files and results are erased.</li>
          <li>The project disappears from your workspace. This can&apos;t be undone.</li>
        </ul>
        <p className="mt-2 text-xs text-muted">A record of what happened is kept in the server&apos;s audit log, but nobody can open it through HMAP.</p>
        {!project.archived && <p className="mt-2 text-xs">Only want it out of the way? Archive it instead.</p>}
        <InlineError error={error} />
      </Dialog>
    </>
  );
}

// ------------------------------------------------------------------ review (approval)

function ReviewPanel({ project, planTasks, onDecided }: { project: Project; planTasks: readonly Task[]; onDecided: () => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const id = useId();
  async function decide(approved: boolean) {
    setBusy(approved ? "approve" : "reject");
    setError(null);
    try {
      await api.decideApproval(project.project_id, approved, comment);
      setComment("");
      onDecided();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }
  const roles = [...new Set(planTasks.map((t) => roleOf(t.capability).name))];
  return (
    <section aria-labelledby={`${id}-t`} className="hm-clipped mb-10 rounded-[3px] p-5 sm:p-7">
      <span aria-hidden="true" className="hm-clip" />
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="hm-key grid size-9 shrink-0 place-items-center rounded-xl bg-warning font-bold text-white [--hm-key-edge:color-mix(in_oklab,var(--hm-warning)_60%,black)] dark:text-canvas">
          !
        </span>
        <h2 id={`${id}-t`} className="pt-1 text-lg font-semibold tracking-tight">
          Your plan is ready. Review it before work continues.
        </h2>
      </div>
      <p className="mt-1 text-sm text-fg-2">
        {planTasks.length} step{planTasks.length === 1 ? "" : "s"}, handled by {roles.join(", ") || "your AI team"}. Check the steps
        below — select one to see what it involves. Nothing runs until you approve.
      </p>
      <div className="mt-3 max-w-xl">
        <Field label="Note (optional)" htmlFor={id} hint="Kept with the decision in the project history.">
          {({ describedBy }) => (
            <textarea id={id} className={cx(textareaClass, "!min-h-14")} rows={2} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} aria-describedby={describedBy} />
          )}
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="primary" busy={busy === "approve"} disabled={busy !== null} onClick={() => void decide(true)}>
          Approve and start
        </Button>
        <Button variant="secondary" busy={busy === "reject"} disabled={busy !== null} onClick={() => void decide(false)}>
          Reject plan
        </Button>
        <span className="text-xs text-muted">Rejecting cancels these steps; you can then run the project again with a changed request.</span>
      </div>
      <div className="mt-2">
        <InlineError error={error} />
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ what we understood

interface RequirementView {
  id: string;
  text: string;
  priority?: string;
  type?: string;
}

function parseRequirements(raw: string): { requirements: RequirementView[]; constraints: string[]; deliverables: string[]; questions: string[] } | null {
  try {
    const v = JSON.parse(raw) as Record<string, unknown>;
    if (!Array.isArray(v.requirements)) return null;
    const list = (key: string, field: string) =>
      Array.isArray(v[key]) ? (v[key] as Record<string, unknown>[]).map((x) => String(x[field] ?? "")).filter(Boolean) : [];
    return {
      requirements: (v.requirements as Record<string, unknown>[]).map((r) => ({
        id: String(r.id ?? ""),
        text: String(r.text ?? ""),
        priority: typeof r.priority === "string" ? r.priority : undefined,
        type: typeof r.type === "string" ? r.type : undefined,
      })),
      constraints: list("constraints", "text"),
      deliverables: list("deliverables", "name"),
      questions: Array.isArray(v.open_questions) ? (v.open_questions as unknown[]).map(String) : [],
    };
  } catch {
    return null;
  }
}

function Understood({ projectId, artifact, stub }: { projectId: string; artifact: ArtifactItem | undefined; stub: boolean }) {
  const { developer } = usePreferences();
  const text = useApiQuery(artifact ? `req:${artifact.artifact_id}@${artifact.version}` : null, (s) =>
    api.artifactText(projectId, artifact!.artifact_id, artifact!.version, s),
  );
  if (!artifact) return <p className="text-sm text-muted">The requirements appear here once your AI team has read the request.</p>;
  if (text.loading) return <LoadingState label="Loading requirements…" />;
  if (text.error) return <ErrorState error={text.error} onRetry={text.reload} />;
  const parsed = text.data ? parseRequirements(text.data) : null;
  if (!parsed) return <FileLinks projectId={projectId} refs={[artifact]} />;
  return (
    <div className="space-y-3">
      {stub && (
        <p className="text-xs text-warning">
          Sample output from a placeholder agent — it does not reflect your actual request.
        </p>
      )}
      <ol className="divide-y divide-line">
        {parsed.requirements.map((r) => (
          <li key={r.id} className="flex gap-3 py-2 text-sm">
            <span className="w-8 shrink-0 font-mono text-2xs text-muted">{r.id}</span>
            <span className="min-w-0 flex-1">{r.text}</span>
            {r.priority && <Badge>{r.priority}</Badge>}
          </li>
        ))}
      </ol>
      {parsed.deliverables.length > 0 && (
        <p className="text-sm">
          <span className="text-muted">Deliverables: </span>
          {parsed.deliverables.join(", ")}
        </p>
      )}
      {parsed.constraints.length > 0 && (
        <p className="text-sm">
          <span className="text-muted">Constraints: </span>
          {parsed.constraints.join("; ")}
        </p>
      )}
      {parsed.questions.length > 0 && (
        <div className="text-sm">
          <p className="text-muted">Open questions</p>
          <ul className="list-disc pl-5">
            {parsed.questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      )}
      {developer && <FileLinks projectId={projectId} refs={[artifact]} />}
    </div>
  );
}

/** The documents of a run side by side per folder they were uploaded from (Part A, Part B, ...). */
function UploadedDocuments({ documents }: { documents: readonly string[] }) {
  const groups = new Map<string | null, string[]>();
  for (const d of documents) {
    const slash = d.lastIndexOf("/");
    const folder = slash > 0 ? d.slice(0, slash) : null;
    groups.set(folder, [...(groups.get(folder) ?? []), slash > 0 ? d.slice(slash + 1) : d]);
  }
  return (
    <div className="flex flex-wrap gap-x-12 gap-y-5">
      {[...groups].map(([folder, names]) => (
        <div key={folder ?? ""} className="min-w-40">
          {folder && (
            <p className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-fg">
              <span aria-hidden="true" className="hm-folder-glyph" />
              {folder}
            </p>
          )}
          <ul className={cx("space-y-1 text-sm text-fg-2", folder && "pl-6")}>
            {names.map((n, i) => (
              <li key={`${n}-${i}`}>{n}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ results

function Results({ projectId, items, run, stubCapabilities }: { projectId: string; items: readonly ArtifactItem[]; run: number; stubCapabilities: ReadonlySet<string> }) {
  const { developer } = usePreferences();
  const mine = items.filter((a) => (a.produced_by ? a.produced_by.run === run : true));
  if (mine.length === 0) return <EmptyState title="No files yet">Results appear here as steps finish.</EmptyState>;
  return (
    <ul className="divide-y divide-line">
      {mine.map((a) => {
        const by = a.produced_by;
        const stub = by ? stubCapabilities.has(by.capability) : false;
        return (
          <li key={`${a.artifact_id}@${a.version}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
            <div className="min-w-0 flex-1">
              <a
                href={api.artifactUrl(projectId, a.artifact_id, a.version)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-medium text-fg hover:text-accent-ink"
              >
                {by ? by.task_title : a.created_by === "user" ? (a.name && a.name !== "request.txt" ? a.name : "Your request") : a.artifact_type.replace(/[-_]/g, " ")}
              </a>
              <p className="text-2xs text-muted">
                {a.artifact_type.replace(/[-_]/g, " ")} · {a.media_type} · {formatBytes(a.size_bytes)} · {formatRelative(a.created_at)}
                {by && ` · by ${roleOf(by.capability).name}${stub ? " (placeholder, sample content)" : ""}`}
              </p>
              {developer && (
                <p className="font-mono text-2xs text-muted">
                  {a.artifact_id} v{a.version} · sha256 {a.sha256.slice(0, 16)}…
                </p>
              )}
            </div>
            <a href={api.artifactUrl(projectId, a.artifact_id, a.version, true)} className="text-xs text-fg-2 hover:text-accent-ink">
              Download
            </a>
          </li>
        );
      })}
    </ul>
  );
}

// ------------------------------------------------------------------ page

export function ProjectDetailView({ projectId }: { projectId: string }) {
  const { developer } = usePreferences();
  const project = useApiQuery(`project:${projectId}`, (s) => api.getProject(projectId, s), { intervalMs: 20_000 });
  const tasks = useApiQuery(`tasks:${projectId}`, (s) => api.listTasks(projectId, s), { intervalMs: 20_000 });
  const artifacts = useApiQuery(`artifacts:${projectId}`, (s) => api.listArtifacts(projectId, s), { intervalMs: 30_000 });
  const caps = useApiQuery("capabilities", (s) => api.listCapabilities(s), { intervalMs: 60_000 });
  const stream = useEventStream({ projectId });
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    // deep link from the event stream: /projects/<id>?task=<task id> opens that step's details
    const task = new URLSearchParams(window.location.search).get("task");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read once after hydration
    if (task) setSelected(task);
  }, []);
  const [pickedRun, setPickedRun] = useState<number | null>(null);
  const [runAgain, setRunAgain] = useState(false);
  const [panel, setPanel] = useState("activity");

  const reloadAll = useCallback(() => {
    project.reload();
    tasks.reload();
    artifacts.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.reload, tasks.reload, artifacts.reload]);
  useEventTrigger(stream.events, (e) => e.project_id === projectId, reloadAll);

  const stubCapabilities = useMemo(() => new Set((caps.data ?? []).filter((c) => c.status !== "real").map((c) => c.capability)), [caps.data]);

  const p = project.data;
  const latest = p ? currentRun(p) : 1;
  const run = pickedRun ?? latest;
  useEffect(() => {
    // a new run appeared (e.g. "Run again"): follow it
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPickedRun(null);
  }, [latest]);

  const allTasks = useMemo(() => tasks.data ?? [], [tasks.data]);
  const runTasks = useMemo(() => allTasks.filter((t) => runOf(t) === run), [allTasks, run]);
  const planTasks = runTasks.filter((t) => t.plan_task_id !== null);
  const titles = useMemo(() => new Map(allTasks.map((t) => [t.task_id, t.title || t.objective])), [allTasks]);

  if (project.loading) return <LoadingState label="Opening project…" />;
  if (project.error) {
    if (isApiError(project.error) && project.error.isNotFound) {
      return (
        <EmptyState title="This project isn't available" action={<Link href="/" className="text-sm text-accent-ink hover:underline">Back to your projects</Link>}>
          It doesn&apos;t exist, was deleted, or belongs to another account.
        </EmptyState>
      );
    }
    return <ErrorState error={project.error} onRetry={reloadAll} />;
  }
  if (!p) return null;

  const st = projectStateText(p.state);
  const isLatest = run === latest;
  const stages = stagesOf(p, allTasks, run);
  const runRec = p.runs?.find((r) => r.number === run);
  const extractArtifact = (artifacts.data ?? []).find((a) => a.produced_by?.capability === "document.extract" && a.produced_by.run === run);
  const waiting = isLatest && p.state === "AWAITING_APPROVAL";
  const active = ACTIVE_PROJECT_STATES.has(p.state);
  const runApprovals = approvalsOfRun(p.approvals ?? [], p.runs ?? [], run);
  const panels: TabItem[] = [
    {
      id: "activity",
      label: "Activity",
      render: () =>
        developer ? (
          <EventLog events={stream.events} status={stream.status} onClear={stream.clear} showProject={false} label="Project events" />
        ) : (
          <ActivityTimeline entries={timelineEntries(stream.events.filter((e) => e.project_id === projectId), (id) => titles.get(id))} emptyText="No activity yet." />
        ),
    },
    {
      id: "history",
      label: `Runs (${p.runs?.length ?? 0})`,
      render: () =>
        p.runs && p.runs.length ? (
          <ol className="divide-y divide-line">
            {[...p.runs].reverse().map((r) => {
              const out = r.outcome ? projectStateText(r.outcome) : r.number === latest ? st : null;
              return (
                <li key={r.number} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
                  <button type="button" onClick={() => setPickedRun(r.number)} className={cx("text-sm font-medium hover:text-accent-ink", r.number === run && "text-accent-ink")}>
                    Run {r.number}
                  </button>
                  {out && <Status tone={out.tone} label={out.label} />}
                  <span className="min-w-0 flex-1 truncate text-xs text-muted">{r.goal ?? documentsSummary(r.documents)}</span>
                  <span className="text-2xs text-muted">
                    {formatDateTime(r.started_at)}
                    {r.task_count ? ` · ${r.task_count} tasks` : ""}
                  </span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-sm text-muted">No runs yet.</p>
        ),
    },
    ...runApprovals.length ? [{
      id: "decisions",
      label: "Decisions",
      render: () => (
        <ol className="divide-y divide-line">
          {[...runApprovals].reverse().map((a) => (
            <li key={a.approval_id} className="py-2 text-sm">
              <span className="font-medium capitalize">{a.status === "approved" && a.comment?.startsWith("auto") ? "Approved automatically" : a.status}</span>
              <span className="ml-2 text-2xs text-muted">{formatDateTime(a.decided_at ?? a.requested_at)}</span>
              {a.comment && !a.comment.startsWith("auto") && <p className="text-fg-2">“{a.comment}”</p>}
            </li>
          ))}
        </ol>
      ),
    }] : [],
    ...PROJECT_PANELS.map((f) => {
      const Panel = f.ProjectPanel!;
      return {
        id: `feature-${f.id}`,
        label: f.title,
        render: () => (
          <ErrorBoundary name={f.title}>
            <Panel projectId={projectId} project={p} tasks={allTasks} events={stream.events} reload={reloadAll} />
          </ErrorBoundary>
        ),
      };
    }),
  ];

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-3 text-xs text-muted">
        <Link href="/" className="hover:text-fg">
          My projects
        </Link>
        <span aria-hidden="true"> / </span>
        <span className="text-fg-2">{p.name}</span>
      </nav>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight sm:text-[1.375rem]">{p.name}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <Status tone={st.tone} label={st.label} live={active && p.state !== "AWAITING_APPROVAL"} />
            <span className="text-sm text-fg-2">{p.stopped_reason && p.state === "CANCELLED" ? `Stopped: ${p.stopped_reason}.` : st.explain}</span>
          </div>
          <p className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-2xs text-muted">
            <span>{p.auto_approve ? "Runs automatically (no review step)" : "Pauses for your review of each plan"}</span>
            <span>{p.cloud_ok === false ? "Kept on this computer (no cloud models)" : "Cloud models allowed"}</span>
            {p.archived && <span>Archived</span>}
            {developer && <Mono>{p.project_id}</Mono>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {active && <StopProjectButton projectId={projectId} onStopped={reloadAll} />}
          {FINISHED.has(p.state) && (
            <Button variant="primary" onClick={() => setRunAgain(true)}>
              Run again
            </Button>
          )}
          <MoreMenu project={p} onChanged={reloadAll} />
        </div>
      </header>
      <RunAgainDialog key={latest} project={p} open={runAgain} onClose={() => setRunAgain(false)} onStarted={reloadAll} />

      {p.auto_approve && active && (
        <p className="mb-6 text-sm text-fg-2">
          <span className="font-medium text-fg">Automatic mode:</span> the requirements and plan are shown below and work continues without a
          review step. Press <span className="font-medium text-danger">Stop</span> at any time to halt everything.
        </p>
      )}

      {(p.runs?.length ?? 0) > 1 && (
        <div role="tablist" aria-label="Runs" className="mb-5 flex flex-wrap gap-1">
          {p.runs!.map((r) => (
            <button
              key={r.number}
              type="button"
              role="tab"
              aria-selected={r.number === run}
              onClick={() => setPickedRun(r.number)}
              className={cx("rounded px-2 py-1 text-xs", r.number === run ? "bg-selected font-medium" : "text-muted hover:bg-hover hover:text-fg")}
            >
              Run {r.number}
              {r.number === latest ? " (latest)" : ""}
            </button>
          ))}
        </div>
      )}
      {!isLatest && runRec && (
        <p className="mb-5 text-xs text-muted">
          Viewing an earlier run from {formatDateTime(runRec.started_at)}. <button type="button" className="text-accent-ink hover:underline" onClick={() => setPickedRun(null)}>Show the latest run</button>
        </p>
      )}

      <div className="mb-8">
        <StageRail stages={stages} selectedTaskId={selected} onSelectTask={setSelected} />
      </div>

      {waiting && <ReviewPanel project={p} planTasks={planTasks} onDecided={reloadAll} />}

      <div className={cx("grid gap-8", selected && "lg:grid-cols-[minmax(0,1fr)_22rem]")}>
        <div className="min-w-0 space-y-10">
          {runRec?.goal && (
            <Section title="Your request">
              <p className="text-sm leading-relaxed whitespace-pre-wrap text-fg-2">{runRec.goal}</p>
            </Section>
          )}
          {!runRec?.goal && runRec && runRec.documents.length > 0 && (
            <Section title="Your documents" description={documentsSummary(runRec.documents)}>
              <UploadedDocuments documents={runRec.documents} />
            </Section>
          )}
          <Section title="What your AI team understood" description="The requirements pulled out of your request. Check them before approving the plan.">
            {artifacts.loading ? <LoadingState /> : <Understood projectId={projectId} artifact={extractArtifact} stub={stubCapabilities.has("document.extract")} />}
          </Section>
          <Section
            title="Plan"
            description={planTasks.length ? `${planTasks.length} steps. Select a step to see its details.` : undefined}
          >
            {tasks.loading ? (
              <LoadingState />
            ) : planTasks.length === 0 ? (
              <p className="text-sm text-muted">The plan appears here once it has been prepared.</p>
            ) : (
              <PlanGraph tasks={planTasks} selectedTaskId={selected} onSelectTask={setSelected} stubCapabilities={stubCapabilities} />
            )}
          </Section>
          <Section title="Results and files" description="Everything your AI team produced in this run. Files are private to your account.">
            {artifacts.loading ? <LoadingState /> : artifacts.error ? <ErrorState error={artifacts.error} onRetry={artifacts.reload} /> : (
              <Results projectId={projectId} items={artifacts.data ?? []} run={run} stubCapabilities={stubCapabilities} />
            )}
          </Section>
          <section aria-label="Project history">
            <Tabs tabs={panels} selected={panel} onSelect={setPanel} label="Project history" />
          </section>
        </div>
        {selected && (
          <div className="min-w-0 lg:sticky lg:top-6 lg:self-start">
            <TaskInspector
              key={selected}
              projectId={projectId}
              taskId={selected}
              events={stream.events}
              stubCapabilities={stubCapabilities}
              onClose={() => setSelected(null)}
              onChanged={reloadAll}
            />
          </div>
        )}
      </div>
    </>
  );
}
