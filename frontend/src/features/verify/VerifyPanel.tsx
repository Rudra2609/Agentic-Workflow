"use client";

import { useState } from "react";

import { Badge, Button, EmptyState, ErrorState, InlineError, LoadingState, Mono, Section, Spinner, Status, cx } from "@/components/ui";
import type { ProjectPanelProps } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { usePreferences } from "@/lib/preferences";
import { useApiQuery } from "@/lib/useApiQuery";

import { getPage, getRun, listRuns, requestFollowUp } from "./client";
import { VERDICT_TEXT, excerpt, host, isFlagged, layerSteps, percent, safeHref, sortClaims, verifyEventKey } from "./logic";
import type { ClaimCheck, Comparison, EvidenceView, RunDetail, RunSummary, Verdict } from "./types";

/** Project tab "Verification" (Member 6): each verification step's claim table with verdict chips, the quote next
 * to the saved page, conflicting sources, every layer's result, and a "request more research" button. */
export function VerifyPanel({ projectId, events, reload }: ProjectPanelProps) {
  const { developer } = usePreferences();
  const runs = useApiQuery(`verify:${projectId}:${verifyEventKey(events)}`, (signal) => listRuns(projectId, signal));
  const [selected, setSelected] = useState<string | null>(null);
  const list = runs.data ?? [];
  const current = list.find((r) => r.task_id === selected) ?? list[0];

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Verification"
        description="Every research finding is checked on its own: is each quote really in the saved page, does it say what the finding claims, and does another source disagree? Doubtful findings go back for more research."
      >
        {runs.loading ? (
          <LoadingState label="Loading the checks…" />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={runs.reload} />
        ) : list.length === 0 ? (
          <EmptyState title="Nothing checked yet">The plan&apos;s verification step runs after its research step.</EmptyState>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Verification steps">
            {list.map((r) => (
              <li key={r.task_id}>
                <RunCard run={r} active={current?.task_id === r.task_id} onSelect={() => setSelected(r.task_id)} />
              </li>
            ))}
          </ul>
        )}
      </Section>
      {current && <Detail key={`${current.task_id}:${current.status}`} projectId={projectId} summary={current} developer={developer} onFollowUp={() => { runs.reload(); reload(); }} />}
    </div>
  );
}

function Chip({ verdict, confidence }: { verdict: Verdict; confidence?: number }) {
  const v = VERDICT_TEXT[verdict];
  return <Status tone={v.tone} label={v.label} title={`${v.help}${confidence !== undefined ? ` Confidence ${percent(confidence)}.` : ""}`} />;
}

function RunCard({ run, active, onSelect }: { run: RunSummary; active: boolean; onSelect: () => void }) {
  const flagged = run.unsupported + run.conflicting + run.needs_more;
  return (
    <button type="button" onClick={onSelect} aria-pressed={active} className={cx("flex w-full flex-col gap-1.5 rounded-md border px-3 py-2.5 text-left", active ? "border-accent bg-selected" : "border-line bg-surface hover:bg-hover")}>
      <span className="flex items-start justify-between gap-2">
        <span className="text-sm font-semibold text-fg">{run.round > 0 ? `Re-check after follow-up research (round ${run.round})` : "Check of the research findings"}</span>
        {run.status === "running" ? <Spinner className="size-3 shrink-0" label="checking" /> : <Badge>{run.claims} findings</Badge>}
      </span>
      <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-fg-2">
        <span className="text-success">{run.verified} verified</span>
        {run.unsupported > 0 && <span className="text-danger">{run.unsupported} unsupported</span>}
        {run.conflicting > 0 && <span className="text-warning">{run.conflicting} conflicting</span>}
        {run.needs_more > 0 && <span>{run.needs_more} need more research</span>}
      </span>
      <span className="text-xs text-muted">{run.claims === 0 ? "No research findings to check." : flagged ? `${flagged} finding${flagged === 1 ? "" : "s"} flagged` : "Every finding checks out."}</span>
    </button>
  );
}

function Detail({ projectId, summary, developer, onFollowUp }: { projectId: string; summary: RunSummary; developer: boolean; onFollowUp: () => void }) {
  const run = useApiQuery(`verify:run:${projectId}:${summary.task_id}:${summary.status}`, (signal) => getRun(projectId, summary.task_id, signal));
  const [open, setOpen] = useState<string | null>(null);
  if (run.loading) return <LoadingState label="Loading the check…" />;
  if (run.error) return <ErrorState error={run.error} onRetry={run.reload} />;
  const d = run.data;
  if (!d) return null;
  const claims = sortClaims(d.trace.claims);
  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Findings checked"
        description={`Layers: ${d.trace.layers.map((l) => l.toUpperCase()).join(" → ")}${developer ? ` · ${d.trace.model_calls} model calls · ${d.trace.tokens.toLocaleString()} tokens · ${d.trace.seconds.toFixed(1)} s` : ""}`}
        actions={<span className="text-xs text-muted">{summary.finished_at ? formatDateTime(summary.finished_at) : null}</span>}
      >
        {claims.length === 0 ? (
          <p className="text-sm text-muted">{d.trace.notes[0] ?? "No findings to check."}</p>
        ) : (
          <ul className="flex flex-col gap-2" aria-label="Checked findings">
            {claims.map((c) => (
              <li key={c.claim_id}>
                <ClaimRow claim={c} open={open === c.claim_id} onToggle={() => setOpen(open === c.claim_id ? null : c.claim_id)} projectId={projectId} researchTaskId={d.trace.research_task_id} developer={developer} />
              </li>
            ))}
          </ul>
        )}
      </Section>
      <FollowUp detail={d} projectId={projectId} taskId={summary.task_id} onDone={() => { run.reload(); onFollowUp(); }} />
    </div>
  );
}

function ClaimRow({ claim, open, onToggle, projectId, researchTaskId, developer }: { claim: ClaimCheck; open: boolean; onToggle: () => void; projectId: string; researchTaskId: string | null; developer: boolean }) {
  return (
    <div className={cx("rounded-md border bg-surface", isFlagged(claim.verdict) ? "border-line-strong" : "border-line")}>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full flex-col gap-1 px-3 py-2.5 text-left hover:bg-hover sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <span className="min-w-0 text-sm text-fg">
          <Mono className="mr-1.5 text-muted">{claim.claim_id}</Mono>
          {claim.text}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <Chip verdict={claim.verdict} confidence={claim.confidence} />
          {developer && <span className="text-xs tabular-nums text-muted">{percent(claim.confidence)}</span>}
        </span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-line px-3 py-3">
          <p className="text-xs text-fg-2">{claim.explanation}</p>
          {claim.atoms.length > 1 && <p className="text-xs text-muted">Checked as {claim.atoms.length} separate statements; the worst one decides.</p>}
          {claim.atoms.filter((a) => a.check_worthy).map((a) => (
            <div key={a.atom_id} className="flex flex-col gap-1">
              {claim.atoms.length > 1 && (
                <p className="text-xs font-medium text-fg">
                  <Mono className="mr-1 text-muted">{a.atom_id}</Mono>“{a.text}” <Chip verdict={a.verdict} />
                </p>
              )}
              <ol className="flex flex-col gap-0.5 text-xs" aria-label={`Layers for ${a.atom_id}`}>
                {layerSteps(a).map((s) => (
                  <li key={s.layer} className="flex gap-2">
                    <span className={cx("w-6 shrink-0 font-semibold", s.state === "pass" ? "text-success" : s.state === "fail" ? "text-danger" : s.state === "warn" ? "text-warning" : "text-muted")}>{s.layer}</span>
                    <span className="text-fg-2">{s.text}</span>
                  </li>
                ))}
              </ol>
              {a.l4.some((c) => c.judgement?.label === "refutes") && <Conflicts comps={a.l4.filter((c) => c.judgement?.label === "refutes")} />}
            </div>
          ))}
          {(claim.evidence ?? []).map((e) => (
            <EvidenceSide key={e.id} evidence={e} projectId={projectId} researchTaskId={researchTaskId} failed={claim.atoms[0]?.l1.find((r) => r.evidence_id === e.id)?.ok === false} />
          ))}
        </div>
      )}
    </div>
  );
}

function Conflicts({ comps }: { comps: Comparison[] }) {
  return (
    <div className="rounded border border-warning bg-warning-soft px-2.5 py-2" aria-label="Conflicting sources">
      <p className="text-xs font-medium text-fg">Another source says otherwise</p>
      {comps.map((c) => {
        const href = safeHref(c.passage.url);
        return (
          <div key={c.passage.url + c.passage.text.slice(0, 20)} className="mt-1.5">
            <blockquote className="border-l-2 border-warning pl-2 text-xs italic text-fg">{c.passage.text}</blockquote>
            <p className="mt-0.5 text-xs text-muted">
              {href ? <a href={href} target="_blank" rel="noreferrer noopener" className="hover:underline">{c.passage.host}</a> : c.passage.host}
              {c.passage.origin === "independent" ? " · found by the verifier's own search" : ""}
              {c.signals.length ? ` · ${c.signals.join(", ")}` : ""}
              {c.judgement?.rationale ? ` · ${c.judgement.rationale}` : ""}
            </p>
          </div>
        );
      })}
    </div>
  );
}

/** The quote next to the saved page it was checked against (the page comes from Member 5's research API). */
function EvidenceSide({ evidence, projectId, researchTaskId, failed }: { evidence: EvidenceView; projectId: string; researchTaskId: string | null; failed: boolean }) {
  const [show, setShow] = useState(false);
  const ref = evidence.page_artifact;
  const page = useApiQuery(show && ref && researchTaskId ? `verify:page:${projectId}:${ref.artifact_id}:${researchTaskId}` : null, (signal) => getPage(projectId, ref!.artifact_id, researchTaskId!, signal));
  const span = page.data?.spans.find((s) => s.evidence_id === evidence.id);
  return (
    <div className="grid gap-2 md:grid-cols-2">
      <div className="min-w-0">
        <p className="text-xs text-muted"><Mono>{evidence.id}</Mono> · {host(evidence.url)}{evidence.title ? ` · ${evidence.title}` : ""}</p>
        <blockquote className={cx("mt-1 border-l-2 pl-2 text-xs italic text-fg", failed ? "border-danger" : "border-accent")}>{evidence.quote}</blockquote>
        {failed && <p className="mt-1 text-xs text-danger">This quote is not in the saved page word for word.</p>}
      </div>
      <div className="min-w-0 rounded border border-line bg-surface-2 px-2 py-1.5">
        {!show ? (
          <Button size="sm" variant="ghost" onClick={() => setShow(true)} disabled={!ref || !researchTaskId}>Show the saved page</Button>
        ) : page.loading ? (
          <LoadingState label="Loading the saved page…" />
        ) : page.error ? (
          <InlineError error={page.error} />
        ) : page.data ? (
          <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-fg-2">
            {span ? (() => {
              const ex = excerpt(page.data.text, span.start, span.end);
              return (<>{ex.cutStart && "… "}{ex.before}<mark className="rounded bg-warning-soft px-0.5 text-fg">{ex.mark}</mark>{ex.after}{ex.cutEnd && " …"}</>);
            })() : <span className="text-danger">The quote was not found in this page. Start of the page: {page.data.text.slice(0, 400)}…</span>}
            <span className="mt-1 block text-muted">sha256 <Mono>{page.data.content_sha256.slice(0, 12)}</Mono></span>
          </p>
        ) : null}
      </div>
    </div>
  );
}

function FollowUp({ detail, projectId, taskId, onDone }: { detail: RunDetail; projectId: string; taskId: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const flagged = detail.trace.claims.filter((c) => isFlagged(c.verdict));
  async function ask() {
    setBusy(true);
    setError(null);
    try {
      await requestFollowUp(projectId, taskId, flagged.map((c) => c.claim_id));
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Section title="Follow-up research" description="Flagged findings become new research questions; a re-check runs when that research is done (at most 3 rounds).">
      {detail.follow_ups.length > 0 && (
        <ul className="mb-3 flex flex-col gap-1 text-xs text-fg-2" aria-label="Follow-up steps">
          {detail.follow_ups.map((t) => (
            <li key={t.task_id}><Mono>{t.capability}</Mono> {t.objective} — {t.state.toLowerCase()}</li>
          ))}
        </ul>
      )}
      {detail.trace.follow_up_questions.length > 0 && (
        <ul className="mb-3 list-disc pl-5 text-xs text-fg-2" aria-label="Questions for follow-up research">
          {detail.trace.follow_up_questions.map((q) => <li key={q}>{q}</li>)}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => void ask()} busy={busy} disabled={flagged.length === 0}>Request more research</Button>
        {flagged.length === 0 && <span className="text-xs text-muted">Nothing flagged.</span>}
        <InlineError error={error} />
      </div>
    </Section>
  );
}
