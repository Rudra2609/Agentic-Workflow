"use client";

import Link from "next/link";
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
  Status,
  Table,
  cx,
  inputClass,
  td,
  textareaClass,
  th,
} from "@/components/ui";
import type { ProjectPanelProps } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

import { acceptReport, getReport, listRounds, overrideItem, requestChanges } from "./client";
import {
  ACTION_TEXT,
  CATEGORY_TEXT,
  KIND_TEXT,
  RECOMMENDATION_TEXT,
  RECOMMENDATION_TONE,
  SOURCE_TEXT,
  VERDICT_TONE,
  counts,
  percent,
  reviewEventKey,
  sortItems,
  taskLabel,
} from "./logic";
import type { Decided, ReportDetail, Round, Verdict } from "./types";

/** Project tab "Review" (Member 10): each review round's verdict per requirement, the marks, failures traced to the
 * step that caused them, the recovery timeline, and a person's override / accept / request changes. */
export function ReviewPanel({ projectId, events, reload }: ProjectPanelProps) {
  const key = reviewEventKey(events);
  const rounds = useApiQuery(`review:${projectId}:${key}`, (signal) => listRounds(projectId, signal));
  const [selected, setSelected] = useState<string | null>(null);
  const list = rounds.data?.rounds ?? [];
  const done = list.filter((r) => r.recommendation);
  const current = done.find((r) => r.task_id === selected) ?? done.at(-1);

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Final review"
        description="The review agent checks the finished work against every requirement, constraint and deliverable: objective evidence first (tests, verified claims, documents that exist), a judge model only for what the checks cannot decide. Each failure is traced to the step that caused it, and only that step and what depends on it run again."
      >
        {rounds.loading ? (
          <LoadingState label="Loading the reviews…" />
        ) : rounds.error ? (
          <ErrorState error={rounds.error} onRetry={rounds.reload} />
        ) : list.length === 0 ? (
          <EmptyState title="No review yet">
            The final review runs when every other step of the plan is finished.
          </EmptyState>
        ) : (
          <Timeline rounds={list} current={current?.task_id} onSelect={setSelected} />
        )}
      </Section>
      {current && (
        <Detail
          key={`${current.task_id}:${key}`}
          projectId={projectId}
          round={current}
          projectState={rounds.data?.project_state ?? ""}
          onChange={() => {
            rounds.reload();
            reload();
          }}
        />
      )}
    </div>
  );
}

function Timeline({
  rounds,
  current,
  onSelect,
}: {
  rounds: Round[];
  current: string | undefined;
  onSelect: (id: string) => void;
}) {
  return (
    <ol className="flex flex-col gap-2" aria-label="Review rounds">
      {rounds.map((r) => (
        <li key={r.task_id}>
          <button
            type="button"
            disabled={!r.recommendation}
            onClick={() => onSelect(r.task_id)}
            aria-pressed={current === r.task_id}
            className={cx(
              "flex w-full flex-col gap-1 rounded-md border px-3 py-2.5 text-left disabled:cursor-default",
              current === r.task_id ? "border-accent bg-selected" : "border-line bg-surface hover:bg-hover",
            )}
          >
            <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-fg">
              Round {r.round}
              {r.recommendation ? (
                <Status
                  tone={RECOMMENDATION_TONE[r.recommendation]}
                  label={RECOMMENDATION_TEXT[r.recommendation]}
                />
              ) : (
                <Status tone="progress" label={r.state.toLowerCase()} live />
              )}
              {r.completeness != null && <Badge>{percent(r.completeness)} complete</Badge>}
              {r.stale_of && <Badge title="the work changed while it was reviewed">re-check</Badge>}
              {r.decision?.accepted && <Badge>accepted by a person</Badge>}
            </span>
            {r.recommendation && (
              <span className="text-xs text-muted">
                {r.failures} failure{r.failures === 1 ? "" : "s"}
                {r.created_at ? ` · ${formatDateTime(r.created_at)}` : ""}
              </span>
            )}
            {r.stop_reason && <span className="text-xs text-warning">Stopped: {r.stop_reason}</span>}
            {r.created_tasks.length > 0 && (
              <span className="text-xs text-fg-2">
                Next:{" "}
                {r.created_tasks
                  .map((t) => `${ACTION_TEXT[t.action ?? ""] ?? t.action} ${t.title ?? t.capability}`)
                  .join(" → ")}
              </span>
            )}
          </button>
        </li>
      ))}
    </ol>
  );
}

function Detail({
  projectId,
  round,
  projectState,
  onChange,
}: {
  projectId: string;
  round: Round;
  projectState: string;
  onChange: () => void;
}) {
  const detail = useApiQuery(`review-detail:${projectId}:${round.task_id}`, (signal) =>
    getReport(projectId, round.task_id, signal),
  );
  if (detail.loading) return <LoadingState label="Loading the review…" />;
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;
  const d = detail.data;
  if (!d) return null;
  const changed = () => {
    detail.reload();
    onChange();
  };
  return (
    <>
      <Matrix projectId={projectId} round={round} detail={d} onChange={changed} />
      <Marks detail={d} />
      <Failures detail={d} />
      <Decisions projectId={projectId} round={round} detail={d} projectState={projectState} onChange={changed} />
    </>
  );
}

function Matrix({
  projectId,
  round,
  detail,
  onChange,
}: {
  projectId: string;
  round: Round;
  detail: ReportDetail;
  onChange: () => void;
}) {
  const items = sortItems(detail.items);
  const n = counts(detail.items);
  return (
    <Section
      title={`Round ${round.round}: requirements`}
      description={`${n.PASS} pass · ${n.PARTIAL} partial · ${n.FAIL} fail${detail.mode ? ` · ${detail.mode} project` : ""}`}
    >
      <Table label="Requirement verdicts" minWidth="44rem">
        <thead>
          <tr>
            <th className={th}>Item</th>
            <th className={th}>Verdict</th>
            <th className={th}>Why</th>
            <th className={th}>Decided by</th>
            <th className={th}>Set</th>
          </tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <ItemRow key={d.item.id} projectId={projectId} taskId={round.task_id} d={d} onChange={onChange} />
          ))}
        </tbody>
      </Table>
    </Section>
  );
}

function ItemRow({
  projectId,
  taskId,
  d,
  onChange,
}: {
  projectId: string;
  taskId: string;
  d: Decided;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const set = async (verdict: Verdict) => {
    setBusy(true);
    setError(null);
    try {
      await overrideItem(projectId, taskId, d.item.id, verdict, "set in the Review tab");
      onChange();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const ev = d.item.evidence;
  return (
    <tr>
      <td className={td}>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted">
            <Mono>{d.item.id}</Mono> · {KIND_TEXT[d.item.kind]}
            {d.item.priority !== "must" && d.item.kind === "requirement" ? ` (${d.item.priority})` : ""}
          </span>
          <span className="text-sm text-fg">{d.item.text}</span>
        </div>
      </td>
      <td className={td}>
        <Status tone={VERDICT_TONE[d.verdict]} label={d.verdict} />
        {d.order_sensitive && (
          <div className="mt-1 text-2xs text-warning" title="the judge changed its verdict when the evidence order changed">
            order-sensitive
          </div>
        )}
      </td>
      <td className={cx(td, "max-w-md text-xs text-fg-2")}>
        <p>{d.rationale || d.check.reasons.join("; ")}</p>
        {ev.stub && <p className="mt-1 text-muted">Placeholder output of a stub agent.</p>}
        {ev.producer_note && (
          <details className="mt-1">
            <summary className="cursor-pointer text-muted">What the producer claimed</summary>
            <p className="mt-1 italic">{ev.producer_note}</p>
          </details>
        )}
      </td>
      <td className={cx(td, "text-xs text-muted")}>{SOURCE_TEXT[d.source]}</td>
      <td className={td}>
        <div className="flex gap-1" role="group" aria-label={`Set the verdict of ${d.item.id}`}>
          {(["PASS", "PARTIAL", "FAIL"] as const).map((v) => (
            <Button
              key={v}
              size="sm"
              variant={d.verdict === v ? "primary" : "secondary"}
              disabled={busy || d.verdict === v}
              onClick={() => void set(v)}
              aria-label={`${v} for ${d.item.id}`}
            >
              {v[0]}
            </Button>
          ))}
        </div>
        {error != null && <InlineError error={error} />}
      </td>
    </tr>
  );
}

function Marks({ detail }: { detail: ReportDetail }) {
  const criteria = detail.items.filter((d) => d.item.kind === "criterion");
  if (criteria.length === 0) return null;
  const got = criteria.reduce((s, d) => s + (d.score ?? 0), 0);
  const max = criteria.reduce((s, d) => s + (d.item.max_marks ?? 0), 0);
  return (
    <Section title="Marking scheme" description={`${got} / ${max} marks (estimated)`}>
      <ul className="flex flex-col gap-2" aria-label="Rubric scores">
        {criteria.map((d) => (
          <li key={d.item.id} className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span>
              <Mono>{d.item.id}</Mono> {d.item.text}
              {d.level && <Badge className="ml-2 bg-surface-2 text-fg-2">{d.level}</Badge>}
            </span>
            <span className="font-medium">
              {d.score ?? 0} / {d.item.max_marks ?? 0}
            </span>
            <span className="w-full text-xs text-muted">{d.rationale}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Failures({ detail }: { detail: ReportDetail }) {
  const fails = detail.report.failures;
  if (fails.length === 0) return null;
  return (
    <Section title="Failures and the step that caused them">
      <ul className="flex flex-col gap-2" aria-label="Failures">
        {fails.map((f, i) => (
          <li key={`${f.requirement_id}-${i}`} className="rounded-md border border-line bg-surface px-3 py-2 text-sm">
            <span className="flex flex-wrap items-center gap-2">
              <Mono>{f.requirement_id}</Mono>
              <Badge>{CATEGORY_TEXT[f.category] ?? f.category}</Badge>
              {f.responsible_task_id ? (
                <Link
                  href={`/features/ops?task=${encodeURIComponent(f.responsible_task_id)}`}
                  className="text-xs font-medium text-accent-ink hover:underline"
                >
                  {taskLabel(f.responsible_task_id, detail.tasks)}
                </Link>
              ) : (
                <span className="text-xs text-muted">no step covers it (replan)</span>
              )}
            </span>
            <p className="mt-1 text-xs text-fg-2">{f.description}</p>
          </li>
        ))}
      </ul>
      {detail.report.revision_requests.length > 0 && (
        <p className="mt-3 text-xs text-fg-2">
          Plan:{" "}
          {detail.report.revision_requests
            .map((p) => `${ACTION_TEXT[p.action] ?? p.action} ${taskLabel(p.task_id, detail.tasks)}`)
            .join("; ")}
        </p>
      )}
    </Section>
  );
}

function Decisions({
  projectId,
  round,
  detail,
  projectState,
  onChange,
}: {
  projectId: string;
  round: Round;
  detail: ReportDetail;
  projectState: string;
  onChange: () => void;
}) {
  const [notes, setNotes] = useState("");
  const [text, setText] = useState("");
  const [step, setStep] = useState("");
  const [busy, setBusy] = useState<"accept" | "changes" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  const waiting = projectState === "REVIEWING";
  const steps = detail.tasks.filter((t) => t.plan_task_id && t.capability !== "review.final");

  const run = async (what: "accept" | "changes") => {
    setBusy(what);
    setError(null);
    setMessage(null);
    try {
      if (what === "accept") {
        await acceptReport(projectId, round.task_id, notes);
        setMessage("Accepted: the project is complete.");
      } else {
        const r = await requestChanges(projectId, round.task_id, text, step || null);
        setMessage(`${r.created.length} step(s) created.`);
        setText("");
      }
      onChange();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Section
      title="Your decision"
      description={
        waiting
          ? `The review stopped and asks you: ${round.stop_reason ?? detail.trace.stop_reason ?? "the failures could not be fixed automatically"}.`
          : "Accept the work as it is, or ask for changes (to one step, or a replan of the rest)."
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label htmlFor="review-notes" className="text-sm font-medium">
            Accept with notes
          </label>
          <textarea
            id="review-notes"
            className={textareaClass}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. known limitation, explained in the report"
          />
          <Button variant="primary" busy={busy === "accept"} onClick={() => void run("accept")}>
            Accept
          </Button>
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="review-changes" className="text-sm font-medium">
            Request changes
          </label>
          <textarea
            id="review-changes"
            className={textareaClass}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What should change?"
          />
          <label htmlFor="review-step" className="text-xs text-muted">
            Step to revise (empty: replan the remaining work)
          </label>
          <select id="review-step" className={inputClass} value={step} onChange={(e) => setStep(e.target.value)}>
            <option value="">Replan</option>
            {steps.map((t) => (
              <option key={t.task_id} value={t.task_id}>
                {t.title || t.capability}
              </option>
            ))}
          </select>
          <Button busy={busy === "changes"} disabled={!text.trim()} onClick={() => void run("changes")}>
            Request changes
          </Button>
        </div>
      </div>
      {message && (
        <p role="status" className="mt-3 text-sm text-success">
          {message}
        </p>
      )}
      {error != null && <InlineError error={error} />}
    </Section>
  );
}
