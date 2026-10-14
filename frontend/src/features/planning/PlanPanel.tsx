"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  InlineError,
  JsonBlock,
  LoadingState,
  Mono,
  Section,
  Spinner,
  Status,
  Table,
  cx,
  inputClass,
  td,
  textareaClass,
  th,
} from "@/components/ui";
import type { ProjectPanelProps } from "@/lib/features";
import { formatRelative } from "@/lib/format";
import { roleOf } from "@/lib/plain";
import { usePreferences } from "@/lib/preferences";
import { useApiQuery } from "@/lib/useApiQuery";

import { PlanRejected, decidePlan, getCapabilities, getPlan, replan, roadmapUrl, savePlan } from "./client";
import {
  PHASES,
  PHASE_LABEL,
  PRIORITY_LABEL,
  addEdge,
  addTask,
  coverageRows,
  diffPlans,
  groupTree,
  localProblems,
  removeEdge,
  removeTask,
  samePlan,
  stepStatus,
  updateTask,
  wouldCycle,
  type GroupNode,
} from "./logic";
import { PlanGraph } from "./PlanGraph";
import type { PlanPhase, PlanResponse, PlanTask, TaskGraph } from "./types";

type View = "graph" | "steps" | "roadmap" | "coverage" | "versions";
const VIEWS: { id: View; label: string }[] = [
  { id: "graph", label: "Graph" },
  { id: "steps", label: "Steps" },
  { id: "roadmap", label: "Roadmap" },
  { id: "coverage", label: "Coverage" },
  { id: "versions", label: "Versions" },
];
const FROZEN = new Set(["COMPLETED", "ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_SUBMITTED", "REVIEWING", "NEEDS_REVISION", "RETRY_SCHEDULED"]);
const BUSY_TASK = new Set(["CREATED", "READY", "ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_SUBMITTED", "RETRY_SCHEDULED"]);

/** Project tab "Plan": the steps the Planner made from the requirements; review, edit, approve or change them. */
export function PlanPanel({ projectId, project, tasks, events, reload }: ProjectPanelProps) {
  const { developer, theme } = usePreferences();
  const planners = useMemo(
    () => tasks.filter((t) => t.capability === "plan.generate" || t.capability === "plan.replan").sort((a, b) => a.updated_at.localeCompare(b.updated_at)),
    [tasks],
  );
  const lastPlanner = planners.at(-1);
  const planning = Boolean(lastPlanner && BUSY_TASK.has(lastPlanner.state));
  const [tick, setTick] = useState(0);
  const stateKey = tasks.filter((t) => t.plan_task_id).map((t) => t.state).join(",");
  const key = `${projectId}:${lastPlanner?.task_id ?? "-"}:${lastPlanner?.state ?? ""}:${project.state}:${project.graph_version ?? 0}:${stateKey}:${tick}`;
  const query = useApiQuery(key, (signal) => getPlan(projectId, signal));
  const caps = useApiQuery("planning:capabilities", (signal) => getCapabilities(signal));
  const data = query.data;

  const [view, setView] = useState<View>("graph");
  const [draft, setDraft] = useState<TaskGraph | null>(null);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [serverIssues, setServerIssues] = useState<string[]>([]);
  const [dialog, setDialog] = useState<"approve" | "reject" | "replan" | null>(null);
  const [text, setText] = useState("");
  const [compare, setCompare] = useState<number | null>(null);

  const loaded = data ? `${data.artifact.artifact_id}@${data.artifact.version}` : null;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a new server version replaces local edits
    setDraft(data ? data.graph : null);
    setEditing(false);
    setServerIssues([]);
  }, [loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const older = useApiQuery(compare ? `${projectId}:v${compare}` : null, (signal) => getPlan(projectId, signal, compare ?? undefined));

  const progress = useMemo(() => {
    if (!lastPlanner) return null;
    const p = [...events].reverse().find((e) => e.event_type === "task.progress" && e.aggregate_id === lastPlanner.task_id);
    return (p?.data?.summary as string | undefined) ?? null;
  }, [events, lastPlanner]);

  if (query.loading) return <LoadingState label="Loading the plan…" />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.reload} />;
  if (!data || !draft) {
    if (planning) {
      return (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <Spinner label="The Planner is turning the requirements into steps…" />
          {progress && <p className="text-xs text-muted">{progress}</p>}
        </div>
      );
    }
    return (
      <EmptyState title="No plan yet">
        Once the requirements are ready, the Planner splits the work into steps, decides what can run at the same time,
        and shows the plan here for you to check before any work starts.
      </EmptyState>
    );
  }

  const g = draft;
  const report = data.report;
  const current = data.submitted_version === data.artifact.version;
  const awaiting = current && data.project_state === "AWAITING_APPROVAL";
  const canEdit = current && Object.keys(data.states).length > 0 && !planning;
  const dirty = !samePlan(g, data.graph);
  const problems = localProblems(g);
  const critical = new Set(report?.schedule.critical_path ?? []);
  const byId = new Map(g.tasks.map((t) => [t.id, t]));
  const sel = selected ? byId.get(selected) ?? null : null;
  const frozen = (id: string) => FROZEN.has(data.states[id] ?? "");

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setActionError(null);
    setServerIssues([]);
    try {
      await fn();
      setTick((n) => n + 1);
      reload();
      return true;
    } catch (err) {
      if (err instanceof PlanRejected) setServerIssues(err.issues.map((i) => i.message));
      setActionError(err);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function submitDialog(e: FormEvent) {
    e.preventDefault();
    const ok = dialog === "approve"
      ? await act("approve", () => decidePlan(projectId, true, data!.artifact.version, text.trim() || undefined))
      : dialog === "reject"
      ? await act("reject", () => decidePlan(projectId, false, data!.artifact.version, text))
      : await act("replan", () => replan(projectId, text, Object.entries(data!.states).filter(([, s]) => ["FAILED", "DEAD_LETTERED", "BLOCKED"].includes(s)).map(([id]) => id)));
    if (ok) {
      setDialog(null);
      setText("");
    }
  }
  const save = () => act("save", () => savePlan(projectId, data.artifact.artifact_id, data.artifact.version, g));

  function connect(before: string, after: string) {
    if (frozen(after)) return setActionError(new Error(`${after} has started or finished; its dependencies cannot change.`));
    if (wouldCycle(g, before, after)) return setActionError(new Error(`${after} cannot wait for ${before}: the steps would wait for each other forever.`));
    setActionError(null);
    setDraft(addEdge(g, before, after));
  }
  function disconnect(before: string, after: string) {
    if (frozen(after)) return;
    if (window.confirm(`Let ${after} start without waiting for ${before}?`)) setDraft(removeEdge(g, before, after));
  }

  const failedSteps = Object.values(data.states).filter((s) => ["FAILED", "DEAD_LETTERED", "BLOCKED"].includes(s)).length;
  const status = planning
    ? { tone: "progress" as const, label: "Planning…" }
    : awaiting
      ? { tone: "warning" as const, label: "Waiting for your approval" }
      : !current
        ? { tone: "muted" as const, label: "Not active (a newer version or run exists)" }
        : data.project_state === "COMPLETED"
          ? { tone: "success" as const, label: "All steps done" }
          : data.project_state === "EXECUTING"
            ? { tone: "progress" as const, label: "Steps are running" }
            : { tone: "neutral" as const, label: data.project_state.toLowerCase() };

  return (
    <div className="flex flex-col gap-5">
      <Section
        title={
          <span className="inline-flex flex-wrap items-center gap-2">
            Plan <Badge>version {data.artifact.version}</Badge>
            <Status tone={status.tone} label={status.label} live={status.tone === "progress"} />
          </span>
        }
        description={
          report
            ? `${g.tasks.length} steps · about ${report.schedule.total_effort} hours of work · longest chain ${report.schedule.makespan} h over ${report.schedule.layers.length} stages`
            : `${g.tasks.length} steps`
        }
        actions={
          <>
            {awaiting && !editing && (
              <>
                <Button variant="primary" size="sm" busy={busy === "approve"} onClick={() => setDialog("approve")} disabled={busy !== null}>
                  Approve plan…
                </Button>
                <Button size="sm" onClick={() => setDialog("reject")} disabled={busy !== null}>
                  Reject…
                </Button>
              </>
            )}
            {canEdit && !editing && (
              <>
                <Button size="sm" onClick={() => { setEditing(true); setView("graph"); }} disabled={busy !== null}>
                  Edit
                </Button>
                <Button size="sm" onClick={() => setDialog("replan")} disabled={busy !== null}>
                  Change plan…
                </Button>
              </>
            )}
            {editing && (
              <>
                <Button variant="primary" size="sm" busy={busy === "save"} disabled={!dirty || problems.length > 0 || busy !== null} onClick={save}>
                  Save as version {data.artifact.version + 1}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => { setDraft(data.graph); setEditing(false); setActionError(null); }}>
                  Discard
                </Button>
              </>
            )}
            <a className="text-xs text-accent-ink underline underline-offset-2" href={roadmapUrl(projectId)}>
              Download roadmap
            </a>
          </>
        }
      >
        {data.requirements.changed && (
          <p className="mb-3 rounded-[5px] border border-warning/40 bg-warning-soft px-3 py-2 text-sm text-fg">
            The requirements were edited after this plan was made.{" "}
            {canEdit && (
              <button type="button" className="font-medium text-accent-ink underline" onClick={() => setDialog("replan")}>
                Update the plan
              </button>
            )}
          </p>
        )}
        {failedSteps > 0 && canEdit && (
          <p className="mb-3 rounded-[5px] border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-fg">
            {failedSteps} step{failedSteps === 1 ? "" : "s"} failed or could not start. “Change plan…” runs them again and
            keeps the finished work.
          </p>
        )}
        {report && (report.questions.length > 0 || Object.keys(report.flagged).length > 0) && (
          <div className="mb-3 grid gap-3 md:grid-cols-2">
            {report.questions.length > 0 && (
              <div className="rounded-[5px] border border-line bg-surface p-3">
                <h3 className="text-xs font-semibold text-fg">Check before approving</h3>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-fg-2">
                  {report.questions.map((q) => <li key={q}>{q}</li>)}
                </ul>
              </div>
            )}
            {Object.keys(report.flagged).length > 0 && (
              <div className="rounded-[5px] border border-line bg-surface p-3">
                <h3 className="text-xs font-semibold text-fg">Not given to an agent (you do these)</h3>
                <ul className="mt-1 space-y-1 text-sm text-fg-2">
                  {Object.entries(report.flagged).map(([rid, why]) => (
                    <li key={rid}><Mono>{rid}</Mono> {why}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        {(problems.length > 0 || serverIssues.length > 0) && editing && (
          <ul className="mb-3 list-disc rounded-[5px] border border-danger/40 bg-danger-soft py-2 pr-3 pl-7 text-sm text-fg">
            {[...problems, ...serverIssues].map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}
        {actionError != null && !(actionError instanceof PlanRejected && editing) && <InlineError error={actionError} />}

        <div role="tablist" aria-label="Plan views" className="mb-3 flex flex-wrap gap-1">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              role="tab"
              type="button"
              aria-selected={view === v.id}
              onClick={() => setView(v.id)}
              className={cx("rounded-[5px] px-3 py-1.5 text-xs font-medium", view === v.id ? "bg-selected text-fg" : "text-muted hover:bg-hover")}
            >
              {v.label}
            </button>
          ))}
        </div>

        {view === "graph" && (
          <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="min-w-0">
              <PlanGraph
                tasks={g.tasks}
                states={data.states}
                critical={critical}
                selectedId={selected}
                editing={editing}
                colorMode={theme}
                onSelect={setSelected}
                onConnect={connect}
                onRemoveEdge={disconnect}
              />
              <p className="mt-1.5 text-xs text-muted">
                {editing
                  ? "Drag from a step's right edge to another step to make it wait; click a connection to remove it."
                  : "Steps on the left come first; steps in the same column can run at the same time. The outlined chain is the critical path."}
              </p>
              {editing && <AddStep graph={g} caps={caps.data?.by_phase} onAdd={(next, id) => { setDraft(next); setSelected(id); }} />}
            </div>
            <StepPanel
              task={sel}
              state={sel ? data.states[sel.id] : undefined}
              editing={editing && sel !== null && !frozen(sel.id)}
              critical={sel ? critical.has(sel.id) : false}
              slack={sel ? report?.schedule.slack[sel.id] : undefined}
              capsByPhase={caps.data?.by_phase}
              requirementIds={Object.keys(g.coverage_matrix)}
              onChange={(patch) => sel && setDraft(updateTask(g, sel.id, patch))}
              onRemove={() => {
                if (sel && window.confirm(`Remove ${sel.id} (${sel.title})?`)) {
                  setDraft(removeTask(g, sel.id));
                  setSelected(null);
                }
              }}
            />
          </div>
        )}
        {view === "steps" && <StepsTable graph={g} states={data.states} critical={critical} onPick={(id) => { setSelected(id); setView("graph"); }} />}
        {view === "roadmap" && <RoadmapView graph={g} data={data} />}
        {view === "coverage" && <CoverageView graph={g} flagged={report?.flagged ?? {}} />}
        {view === "versions" && (
          <VersionsView data={data} compare={compare} setCompare={setCompare} older={older.data ?? null} loading={older.loading} />
        )}
      </Section>

      {developer && report && (
        <Section title="How this plan was made" description="Developer mode">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            <dt className="text-muted">Origin / method</dt><dd>{report.origin} · {report.method} (prompt v{report.prompt_version}, {report.project_kind})</dd>
            <dt className="text-muted">Model calls</dt><dd>{report.llm_calls} {Object.entries(report.answered_by).map(([m, n]) => `${m} ×${n}`).join(", ")}</dd>
            <dt className="text-muted">Fallbacks</dt><dd>{report.fallbacks.join("; ") || "none"}</dd>
            <dt className="text-muted">Dependencies</dt><dd>{Object.entries(report.edges).map(([s, n]) => `${s} ${n}`).join(" · ")}</dd>
            <dt className="text-muted">Repairs</dt><dd>{report.repairs.length ? <ul className="list-disc pl-4">{report.repairs.map((r) => <li key={r}>{r}</li>)}</ul> : "none"}</dd>
            {report.issues.length > 0 && (<><dt className="text-muted">Warnings</dt><dd><ul className="list-disc pl-4">{report.issues.map((i) => <li key={i.message}>{i.message}</li>)}</ul></dd></>)}
          </dl>
          <div className="mt-3"><JsonBlock value={g} summary="Show the TaskGraph JSON" /></div>
        </Section>
      )}

      <Dialog
        open={dialog !== null}
        onClose={() => setDialog(null)}
        title={dialog === "approve" ? `Approve version ${data.artifact.version}` : dialog === "reject" ? "Reject this plan" : "Change the plan"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button>
            <Button variant={dialog === "reject" ? "danger" : "primary"} type="submit" form="plan-dialog" busy={busy !== null}
              disabled={dialog === "reject" && !text.trim()}>
              {dialog === "approve" ? "Approve and start" : dialog === "reject" ? "Reject plan" : "Make a new version"}
            </Button>
          </>
        }
      >
        <form id="plan-dialog" onSubmit={submitDialog} className="flex flex-col gap-2">
          <label htmlFor="plan-dialog-text" className="text-sm text-fg-2">
            {dialog === "approve"
              ? "The steps start in dependency order. A note is optional and is kept with the decision."
              : dialog === "reject"
              ? "Say what is wrong. The steps are cancelled and the project goes back to planning."
              : "What should change? (e.g. “Don't use threads”, “Split the server work into two steps”). Finished steps are kept; the new version needs your approval."}
          </label>
          <textarea id="plan-dialog-text" className={textareaClass} value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} />
        </form>
      </Dialog>
    </div>
  );
}

function AddStep({ graph, caps, onAdd }: { graph: TaskGraph; caps?: Record<string, string[]>; onAdd: (g: TaskGraph, id: string) => void }) {
  const [title, setTitle] = useState("");
  const [phase, setPhase] = useState<PlanPhase>("implement");
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    const cap = caps?.[phase]?.[0] ?? (phase === "test" ? "test.run" : phase === "document" ? "docs.generate" : "code.implement");
    const { graph: next, id } = addTask(graph, title, phase, cap);
    onAdd(next, id);
    setTitle("");
  }
  return (
    <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2">
      <label className="flex min-w-48 flex-1 flex-col text-xs text-muted">
        New step
        <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Add a /quit command" />
      </label>
      <label className="flex flex-col text-xs text-muted">
        Phase
        <select className={inputClass} value={phase} onChange={(e) => setPhase(e.target.value as PlanPhase)}>
          {PHASES.filter((p) => p !== "review").map((p) => <option key={p} value={p}>{PHASE_LABEL[p]}</option>)}
        </select>
      </label>
      <Button type="submit" size="sm">Add step</Button>
    </form>
  );
}

function StepPanel({
  task, state, editing, critical, slack, capsByPhase, requirementIds, onChange, onRemove,
}: {
  task: PlanTask | null;
  state?: string;
  editing: boolean;
  critical: boolean;
  slack?: number;
  capsByPhase?: Record<string, string[]>;
  requirementIds: string[];
  onChange: (patch: Partial<PlanTask>) => void;
  onRemove: () => void;
}) {
  if (!task) {
    return <aside className="rounded-[5px] border border-line bg-surface p-3 text-sm text-muted">Select a step to see its details.</aside>;
  }
  const st = stepStatus(state);
  if (!editing) {
    return (
      <aside className="flex flex-col gap-2 rounded-[5px] border border-line bg-surface p-3 text-sm" aria-label={`Step ${task.id}`}>
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold text-fg"><Mono>{task.id}</Mono> {task.title}</h3>
          <Status tone={st.tone} label={st.label} />
        </div>
        <p className="text-xs text-muted">
          {roleOf(task.agent_capability).name} ({task.agent_capability}) · {PHASE_LABEL[task.phase]} · {PRIORITY_LABEL[task.priority]} priority
          {task.est_effort != null && ` · ${task.est_effort} h`}
          {critical ? " · on the critical path" : slack != null ? ` · can slip ${slack} h` : ""}
        </p>
        {task.description && <p className="text-fg-2">{task.description}</p>}
        {task.requirement_ids.length > 0 && <p className="text-xs">Serves: {task.requirement_ids.map((r) => <Badge key={r} className="mr-1 bg-surface-2">{r}</Badge>)}</p>}
        <div>
          <h4 className="text-xs font-semibold text-fg">Done when</h4>
          <ul className="list-disc pl-4 text-fg-2">{task.acceptance_criteria.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
        {task.research_questions.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-fg">Questions for the Researcher</h4>
            <ul className="list-disc pl-4 text-fg-2">{task.research_questions.map((q) => <li key={q}>{q}</li>)}</ul>
          </div>
        )}
        {task.depends_on.length > 0 && <p className="text-xs text-muted">Waits for: {task.depends_on.join(", ")}</p>}
      </aside>
    );
  }
  const caps = capsByPhase?.[task.phase] ?? [task.agent_capability];
  return (
    <aside className="flex flex-col gap-2 rounded-[5px] border border-line bg-surface p-3 text-sm" aria-label={`Edit step ${task.id}`}>
      <h3 className="font-semibold text-fg">Edit <Mono>{task.id}</Mono></h3>
      <label className="flex flex-col text-xs text-muted">Title
        <input className={inputClass} value={task.title} onChange={(e) => onChange({ title: e.target.value })} />
      </label>
      <label className="flex flex-col text-xs text-muted">Description
        <textarea className={textareaClass} value={task.description} onChange={(e) => onChange({ description: e.target.value })} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col text-xs text-muted">Phase
          <select className={inputClass} value={task.phase} disabled={task.phase === "review"}
            onChange={(e) => {
              const phase = e.target.value as PlanPhase;
              const allowed = capsByPhase?.[phase] ?? [];
              onChange({ phase, agent_capability: allowed.includes(task.agent_capability) ? task.agent_capability : allowed[0] ?? task.agent_capability });
            }}>
            {PHASES.filter((p) => p !== "review" || task.phase === "review").map((p) => <option key={p} value={p}>{PHASE_LABEL[p]}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-muted">Done by
          <select className={inputClass} value={task.agent_capability} onChange={(e) => onChange({ agent_capability: e.target.value })}>
            {caps.map((c) => <option key={c} value={c}>{roleOf(c).name}</option>)}
          </select>
        </label>
      </div>
      <label className="flex flex-col text-xs text-muted">Done when (one per line)
        <textarea className={textareaClass} value={task.acceptance_criteria.join("\n")}
          onChange={(e) => onChange({ acceptance_criteria: e.target.value.split("\n").map((s) => s.trimEnd()).filter((s, i, a) => s || i < a.length - 1) })} />
      </label>
      <fieldset className="text-xs text-muted">
        <legend>Serves requirements</legend>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {requirementIds.map((r) => (
            <label key={r} className="inline-flex items-center gap-1 text-fg-2">
              <input type="checkbox" checked={task.requirement_ids.includes(r)}
                onChange={(e) => onChange({ requirement_ids: e.target.checked ? [...task.requirement_ids, r] : task.requirement_ids.filter((x) => x !== r) })} />
              {r}
            </label>
          ))}
        </div>
      </fieldset>
      {task.phase !== "review" && <Button size="sm" variant="quiet-danger" onClick={onRemove}>Remove step</Button>}
    </aside>
  );
}

function StepsTable({ graph, states, critical, onPick }: { graph: TaskGraph; states: Record<string, string>; critical: ReadonlySet<string>; onPick: (id: string) => void }) {
  return (
    <Table label="Plan steps" minWidth="44rem">
      <thead>
        <tr>
          <th className={th}>Step</th><th className={th}>Done by</th><th className={th}>Phase</th><th className={th}>Waits for</th>
          <th className={th}>Effort</th><th className={th}>Priority</th><th className={th}>Status</th>
        </tr>
      </thead>
      <tbody>
        {graph.tasks.map((t) => {
          const st = stepStatus(states[t.id]);
          return (
            <tr key={t.id}>
              <td className={td}>
                <button type="button" className="text-left text-accent-ink hover:underline" onClick={() => onPick(t.id)}>
                  <Mono>{t.id}</Mono> {t.title}
                </button>
                {critical.has(t.id) && <Badge className="ml-1 bg-accent-soft text-accent-ink">critical</Badge>}
              </td>
              <td className={td}>{roleOf(t.agent_capability).name}</td>
              <td className={td}>{PHASE_LABEL[t.phase]}</td>
              <td className={td}>{t.depends_on.join(", ") || "—"}</td>
              <td className={td}>{t.est_effort ?? "—"} h</td>
              <td className={td}>{PRIORITY_LABEL[t.priority]}</td>
              <td className={td}><Status tone={st.tone} label={st.label} /></td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function RoadmapView({ graph, data }: { graph: TaskGraph; data: PlanResponse }) {
  const tree = groupTree(graph.roadmap.phases);
  const byId = new Map(graph.tasks.map((t) => [t.id, t]));
  const schedule = data.report?.schedule;
  const renderNode = (n: GroupNode, depth: number) => (
    <li key={n.group.id} className={cx(depth > 1 && "ml-4")}>
      <span className={cx(depth === 1 ? "text-sm font-semibold text-fg" : "text-xs font-medium text-fg-2")}>{n.group.name}</span>
      {n.group.task_ids.length > 0 && (
        <ul className="mt-1 mb-2 ml-4 list-disc text-sm text-fg-2">
          {n.group.task_ids.map((id) => <li key={id}><Mono>{id}</Mono> {byId.get(id)?.title ?? id}</li>)}
        </ul>
      )}
      {n.children.length > 0 && <ul>{n.children.map((c) => renderNode(c, depth + 1))}</ul>}
    </li>
  );
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h3 className="mb-2 text-xs font-semibold text-muted">Phases</h3>
        <ul className="space-y-1">{tree.map((n) => renderNode(n, 1))}</ul>
      </div>
      <div className="flex flex-col gap-4">
        <div>
          <h3 className="mb-2 text-xs font-semibold text-muted">Milestones</h3>
          <ol className="list-decimal space-y-1 pl-5 text-sm text-fg-2">
            {graph.roadmap.milestones.map((m) => (
              <li key={m.name}>{m.name} <span className="text-xs text-muted">({m.task_ids.join(", ")})</span></li>
            ))}
          </ol>
        </div>
        {schedule && (
          <>
            <div>
              <h3 className="mb-1 text-xs font-semibold text-muted">Critical path ({schedule.makespan} h)</h3>
              <p className="text-sm text-fg-2">{schedule.critical_path.join(" → ")}</p>
            </div>
            <div>
              <h3 className="mb-1 text-xs font-semibold text-muted">Stages (steps in one stage can run at the same time)</h3>
              <ol className="list-decimal space-y-0.5 pl-5 text-sm text-fg-2">
                {schedule.layers.map((layer, i) => <li key={i}>{layer.join(", ")}</li>)}
              </ol>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function CoverageView({ graph, flagged }: { graph: TaskGraph; flagged: Record<string, string> }) {
  const rows = coverageRows(graph, flagged);
  const missing = rows.filter((r) => r.status === "missing").length;
  return (
    <div>
      <p className="mb-2 text-sm text-fg-2">
        {missing === 0 ? "Every requirement has a step (or is marked for you to do)." : `${missing} requirement${missing === 1 ? " has" : "s have"} no step yet.`}
      </p>
      <Table label="Requirement coverage" minWidth="30rem">
        <thead><tr><th className={th}>Requirement</th><th className={th}>Steps</th><th className={th}>Status</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.requirementId} className={cx(r.status === "missing" && "bg-danger-soft")}>
              <td className={td}><Mono>{r.requirementId}</Mono></td>
              <td className={td}>{r.taskIds.join(", ") || "—"}</td>
              <td className={td}>
                {r.status === "covered" ? <Status tone="success" label="Covered" /> : r.status === "flagged"
                  ? <Status tone="warning" label={`For you: ${r.reason}`} /> : <Status tone="danger" label="No step" />}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

function VersionsView({ data, compare, setCompare, older, loading }: {
  data: PlanResponse; compare: number | null; setCompare: (v: number | null) => void; older: PlanResponse | null; loading: boolean;
}) {
  const diff = older && compare ? diffPlans(older.graph, data.graph) : null;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <ol className="space-y-1 text-sm">
        {[...data.versions].reverse().map((v) => (
          <li key={v.version} className="flex flex-wrap items-center gap-2">
            <Badge>v{v.version}</Badge>
            <span className="text-fg-2">{v.created_by.startsWith("user:") ? "edited by you" : v.version === 1 ? "made by the Planner" : "replanned"}</span>
            <span className="text-xs text-muted">{formatRelative(v.created_at)}</span>
            {v.version === data.submitted_version && <Badge className="bg-accent-soft text-accent-ink">active</Badge>}
            {v.version !== data.artifact.version && (
              <Button size="sm" variant="ghost" onClick={() => setCompare(compare === v.version ? null : v.version)}>
                {compare === v.version ? "Hide changes" : "Compare with latest"}
              </Button>
            )}
          </li>
        ))}
      </ol>
      <div className="text-sm text-fg-2">
        {loading && compare && <Spinner label="Loading…" />}
        {diff && (
          <>
            <h3 className="mb-1 text-xs font-semibold text-muted">Changes from v{compare} to v{data.artifact.version}</h3>
            <ul className="list-disc space-y-0.5 pl-5">
              {diff.added.length > 0 && <li>Added: {diff.added.join(", ")}</li>}
              {diff.removed.length > 0 && <li>Removed: {diff.removed.join(", ")}</li>}
              {diff.changed.length > 0 && <li>Changed: {diff.changed.join(", ")}</li>}
              {diff.edgesAdded.length > 0 && <li>New dependencies: {diff.edgesAdded.join("; ")}</li>}
              {diff.edgesRemoved.length > 0 && <li>Dropped dependencies: {diff.edgesRemoved.join("; ")}</li>}
              {Object.values(diff).every((x) => x.length === 0) && <li>No changes to the steps.</li>}
            </ul>
            {older?.report?.feedback && <p className="mt-2 text-xs">Feedback: “{older.report.feedback}”</p>}
          </>
        )}
        {data.report?.feedback && !diff && <p className="text-xs">This version answers: “{data.report.feedback}”</p>}
      </div>
    </div>
  );
}
