"use client";

import { useMemo, useState } from "react";

import { Badge, Button, EmptyState, ErrorState, InlineError, LoadingState, Mono, Section, Spinner, Status, cx } from "@/components/ui";
import { api } from "@/lib/api";
import type { ProjectPanelProps } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { usePreferences } from "@/lib/preferences";
import { useApiQuery } from "@/lib/useApiQuery";

import { checkAgain, getDiff, getPolicy, getRun, listRuns } from "./client";
import {
  SEVERITY_TEXT,
  SEVERITY_TONE,
  describeChange,
  groupIssues,
  iterationLabel,
  outcomeText,
  percent,
  refineEventKey,
  stopText,
  strategyText,
  subjectLabel,
  totals,
} from "./logic";
import { ScoreCurve } from "./ScoreCurve";
import type { Iteration, RefineRun, RunSummary } from "./types";

const TARGET = 0.9;

/** Project tab "Refinement" (Member 4): how each result was checked and improved — one timeline per refined step:
 * iteration cards (critique, issues by category, what changed), the score curve and why it stopped. */
export function RefinePanel({ projectId, project, events, reload }: ProjectPanelProps) {
  const { developer } = usePreferences();
  const eventKey = refineEventKey(events);
  const runs = useApiQuery(`refine:${projectId}:${eventKey}`, (signal) => listRuns(projectId, signal));
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const on = Boolean(project.refine);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      await api.updateProject(projectId, { refine: !on });
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  // pipeline order (requirements before the plan); by default the newest run that changed something
  const list = useMemo(() => [...(runs.data ?? [])].sort((a, b) => a.started_at.localeCompare(b.started_at)), [runs.data]);
  const current = list.find((r) => r.run_id === selected) ?? [...list].reverse().find((r) => r.applied) ?? list.at(-1);

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Checking and improving results"
        description="Code checks first, then a reviewer model; fixes only what was flagged, and keeps the best version — never a worse one."
        actions={
          <>
            <Status tone={on ? "success" : "muted"} label={on ? "On for this project" : "Off"} />
            <Button size="sm" busy={busy} onClick={() => void toggle()}>
              {on ? "Turn off" : "Turn on"}
            </Button>
            <CheckAgain projectId={projectId} onStarted={() => runs.reload()} />
          </>
        }
      >
        <InlineError error={error} />
        {developer && <PolicyLine />}
      </Section>

      {runs.loading ? (
        <LoadingState label="Loading the checks…" />
      ) : runs.error ? (
        <ErrorState error={runs.error} onRetry={runs.reload} />
      ) : list.length === 0 ? (
        <EmptyState title={on ? "Nothing has been checked yet" : "Results are not being checked"}>
          {on
            ? "The requirements and the plan are checked and improved as they are made; each check appears here with its rounds and scores."
            : "Turn checking on to have the requirements and the plan reviewed and improved before they are used. It is slower: about two extra model calls per round."}
        </EmptyState>
      ) : (
        <>
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Checked results">
            {list.map((r) => (
              <li key={r.run_id}>
                <RunCard run={r} active={current?.run_id === r.run_id} onSelect={() => setSelected(r.run_id)} />
              </li>
            ))}
          </ul>
          {current && <RunDetail key={`${current.run_id}:${current.updated_at}`} projectId={projectId} summary={current} developer={developer} />}
        </>
      )}
    </div>
  );
}

function PolicyLine() {
  const policy = useApiQuery("refine:policy", (signal) => getPolicy(signal));
  if (!policy.data) return null;
  const d = policy.data.default;
  return (
    <p className="text-xs text-muted">
      Stop rules: at most <Mono>{String(d.max_iters)}</Mono> rounds · score ≥ <Mono>{String(d.threshold)}</Mono> · no{" "}
      <Mono>{String(d.no_issues_at_least)}</Mono>+ issue left · plateau <Mono>{String(d.plateau_eps)}</Mono> ×{" "}
      <Mono>{String(d.plateau_k)}</Mono> · budget <Mono>{String(d.budget_tokens)}</Mono> tokens /{" "}
      <Mono>{String(d.budget_seconds)}</Mono> s · hard cap <Mono>{policy.data.hard_max_iters}</Mono>.
    </p>
  );
}

function CheckAgain({ projectId, onStarted }: { projectId: string; onStarted: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const artifacts = useApiQuery(`refine:artifacts:${projectId}`, (signal) => api.listArtifacts(projectId, signal));
  const newest = (type: string) =>
    (artifacts.data ?? []).filter((a) => a.artifact_type === type).sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const targets = [
    { type: "requirement-set", label: "Check the requirements again" },
    { type: "task-graph", label: "Check the plan again" },
  ].filter((t) => newest(t.type));
  if (!targets.length) return null;

  async function start(type: string) {
    const a = newest(type);
    if (!a) return;
    setBusy(type);
    setError(null);
    setDone(null);
    try {
      await checkAgain(projectId, a.artifact_id);
      setDone(type === "task-graph" ? "Checking the plan; an improved plan needs your approval again." : "Checking the requirements…");
      onStarted();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <span className="flex flex-wrap items-center gap-2">
      {targets.map((t) => (
        <Button key={t.type} size="sm" variant="ghost" busy={busy === t.type} onClick={() => void start(t.type)}>
          {t.label}
        </Button>
      ))}
      {done && <span className="text-xs text-muted" role="status">{done}</span>}
      <InlineError error={error} />
    </span>
  );
}

function RunCard({ run, active, onSelect }: { run: RunSummary; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cx(
        "flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2.5 text-left",
        active ? "border-accent bg-selected" : "border-line bg-surface hover:bg-hover",
      )}
    >
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <span className="text-sm font-semibold text-fg">{subjectLabel(run)}</span>
          {run.status === "running" ? <Spinner className="size-3" /> : run.applied ? <Badge className="bg-success-soft text-success">improved</Badge> : <Badge>kept</Badge>}
        </span>
        <span className="mt-0.5 block text-xs text-fg-2">{outcomeText(run)}</span>
      </span>
      <ScoreCurve scores={run.scores} width={84} height={30} compact />
    </button>
  );
}

function RunDetail({ projectId, summary, developer }: { projectId: string; summary: RunSummary; developer: boolean }) {
  const run = useApiQuery(`refine:run:${projectId}:${summary.run_id}:${summary.updated_at}`, (signal) => getRun(projectId, summary.run_id, signal));
  if (run.loading) return <LoadingState label="Loading the rounds…" />;
  if (run.error) return <ErrorState error={run.error} onRetry={run.reload} />;
  const r = run.data;
  if (!r) return null;
  const t = totals(r.iterations);
  return (
    <Section
      title={`${subjectLabel(r)}: ${r.status === "running" ? "checking…" : r.applied ? "improved" : "checked"}`}
      description={`${stopText(r.stop_reason)}${r.error ? ` (${r.error})` : ""}`}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
        <ScoreCurve scores={r.iterations.map((i) => i.score)} width={300} height={110} target={TARGET} />
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted">Score</dt>
          <dd className="text-fg">
            {percent(r.base_score)} → {percent(r.best_score)}
            {r.best_iteration !== null && ` (best: ${iterationLabel(r.best_iteration).toLowerCase()})`}
          </dd>
          <dt className="text-muted">Target</dt>
          <dd className="text-fg">{percent(TARGET)} (dashed line)</dd>
          <dt className="text-muted">Rounds</dt>
          <dd className="text-fg">{Math.max(0, r.iterations.length - 1)}</dd>
          <dt className="text-muted">Used</dt>
          <dd className="text-fg">{r.applied ? "the improved version" : "the original"}</dd>
          {developer && (
            <>
              <dt className="text-muted">Cost</dt>
              <dd className="text-fg">
                {r.tokens.toLocaleString()} tokens · {r.model_calls} model calls · {r.seconds.toFixed(1)} s
              </dd>
              <dt className="text-muted">Critics</dt>
              <dd><Mono>{r.spec.critics.join(", ")}</Mono></dd>
              <dt className="text-muted">Reviser</dt>
              <dd><Mono>{r.spec.reviser}</Mono></dd>
              <dt className="text-muted">Run</dt>
              <dd><Mono>{r.run_id}</Mono> · {formatDateTime(r.started_at)}</dd>
            </>
          )}
          {!developer && t.issues > 0 && (
            <>
              <dt className="text-muted">Problems found</dt>
              <dd className="text-fg">{t.issues} over all rounds</dd>
            </>
          )}
        </dl>
      </div>
      <ol className="mt-5 flex flex-col gap-3" aria-label="Rounds">
        {r.iterations.map((it) => (
          <li key={it.index}>
            <IterationCard projectId={projectId} run={r} it={it} developer={developer} />
          </li>
        ))}
      </ol>
    </Section>
  );
}

function IterationCard({ projectId, run, it, developer }: { projectId: string; run: RefineRun; it: Iteration; developer: boolean }) {
  const groups = useMemo(() => groupIssues(it.critique.issues), [it.critique.issues]);
  const previous = it.index > 0 ? run.iterations[it.index - 1] : undefined;
  const delta = previous ? it.score - previous.score : null;
  const best = run.best_iteration === it.index;
  const strategy = strategyText(it.strategy);
  return (
    <article className={cx("rounded-md border bg-surface px-3 py-3 sm:px-4", best ? "border-accent" : "border-line")} aria-label={iterationLabel(it.index)}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-fg">
          {iterationLabel(it.index)}
          {best && <Badge className="bg-accent-soft text-accent-ink">best</Badge>}
        </h3>
        <span className="text-sm tabular-nums text-fg">
          {percent(it.score)}
          {delta !== null && (
            <span className={cx("ml-1.5 text-xs", delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "text-muted")}>
              {delta > 0 ? "+" : ""}
              {Math.round(delta * 100)}
            </span>
          )}
        </span>
      </header>
      {strategy && <p className="mt-1 text-xs text-fg-2">{strategy}.</p>}
      {it.revision_notes.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs text-fg-2">
          {it.revision_notes.filter((n) => developer || !n.startsWith("strategy:")).slice(0, 8).map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      {developer && it.critics.length > 0 && (
        <p className="mt-2 flex flex-wrap gap-1.5">
          {it.critics.map((c) => (
            <Badge key={c.critic} title={`${c.issues} issue(s)`}>
              {c.critic} {percent(c.score)}
            </Badge>
          ))}
          <Badge>{it.tokens.toLocaleString()} tokens</Badge>
          <Badge>{it.duration_s.toFixed(1)} s</Badge>
        </p>
      )}
      {groups.length === 0 ? (
        <p className="mt-2 text-xs text-success">No problems found.</p>
      ) : (
        <div className="mt-2 flex flex-col gap-1.5">
          {groups.map((g) => (
            <details key={g.category} className="rounded border border-line/70 px-2 py-1.5" open={groups.length <= 2}>
              <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-xs">
                <Status tone={SEVERITY_TONE[g.worst]} label={`${g.label} (${g.issues.length})`} title={g.explain} />
                {developer && <Mono className="text-2xs">{g.category}</Mono>}
              </summary>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {g.issues.map((i, n) => (
                  <li key={n} className="text-xs">
                    <span className={cx("mr-1.5 font-medium", i.severity === "minor" || i.severity === "info" ? "text-warning" : "text-danger")}>
                      {SEVERITY_TEXT[i.severity]}
                    </span>
                    {i.location && <Mono className="mr-1.5 text-2xs">{i.location}</Mono>}
                    <span className="text-fg">{i.description}</span>
                    {i.evidence && <q className="mt-0.5 block break-words text-fg-2 italic">{i.evidence}</q>}
                    {developer && i.fix_hint && <span className="mt-0.5 block text-muted">fix: {i.fix_hint}</span>}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      )}
      {(it.critic_errors?.length ?? 0) > 0 && (
        <p className="mt-2 text-xs text-warning">
          Only the automatic checks scored this round: the reviewing model was not available.
          {developer && <span className="ml-1 text-muted">({it.critic_errors!.join(", ")})</span>}
        </p>
      )}
      {it.reflection && (
        <p className="mt-2 border-l-2 border-info bg-info-soft px-2 py-1 text-xs text-fg">
          <span className="font-medium">What it learned: </span>
          {it.reflection}
        </p>
      )}
      {developer && it.rejected_changes.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-muted">Refused changes ({it.rejected_changes.length})</summary>
          <ul className="mt-1 list-disc pl-5 text-fg-2">
            {it.rejected_changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </details>
      )}
      {it.index > 0 && <Changes projectId={projectId} runId={run.run_id} index={it.index} />}
    </article>
  );
}

function Changes({ projectId, runId, index }: { projectId: string; runId: string; index: number }) {
  const [open, setOpen] = useState(false);
  const diff = useApiQuery(open ? `refine:diff:${runId}:${index}` : null, (signal) => getDiff(projectId, runId, index - 1, index, signal));
  return (
    <div className="mt-2">
      <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? "Hide what changed" : "What changed"}
      </Button>
      {open &&
        (diff.loading ? (
          <Spinner className="size-3" />
        ) : diff.error ? (
          <InlineError error={diff.error} />
        ) : diff.data && diff.data.changes.length === 0 ? (
          <p className="mt-1 text-xs text-muted">Nothing changed in this round.</p>
        ) : (
          <ul className="mt-1.5 flex flex-col gap-1 text-xs">
            {(diff.data?.changes ?? []).map((c, i) => {
              const line = describeChange(c);
              return (
                <li key={i} className={cx("border-l-2 pl-2", line.kind === "added" ? "border-success" : line.kind === "removed" ? "border-danger" : "border-warning")}>
                  <span className="text-fg">{line.text}</span>
                  {line.detail && <span className="block break-words text-fg-2">{line.detail}</span>}
                </li>
              );
            })}
          </ul>
        ))}
    </div>
  );
}
