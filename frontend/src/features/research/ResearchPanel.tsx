"use client";

import { useMemo, useState } from "react";

import { Badge, Button, EmptyState, ErrorState, InlineError, LoadingState, Mono, Section, Spinner, Status, cx, inputClass } from "@/components/ui";
import type { ProjectPanelProps } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { usePreferences } from "@/lib/preferences";
import { useApiQuery } from "@/lib/useApiQuery";

import { getPage, getProviders, getRun, listRuns, startResearch } from "./client";
import {
  KIND_TEXT,
  MODE_TEXT,
  STATUS_TEXT,
  bySource,
  claimsBySub,
  evidenceFor,
  excerpt,
  groupByQuestion,
  host,
  parseQuestions,
  percent,
  researchEventKey,
  safeHref,
  scoreParts,
  sourceNumbers,
  stopText,
} from "./logic";
import type { Evidence, Report, RunDetail, RunSummary, SubQuestion } from "./types";

/** Project tab "Research" (Member 5): each research step's sub-questions with coverage, the cited findings, the
 * sources with their scores, the evidence viewer (quote highlighted in the saved page) and why it stopped. */
export function ResearchPanel({ projectId, events }: ProjectPanelProps) {
  const { developer } = usePreferences();
  const runs = useApiQuery(`research:${projectId}:${researchEventKey(events)}`, (signal) => listRuns(projectId, signal));
  const [selected, setSelected] = useState<string | null>(null);
  const list = runs.data ?? [];
  const current = list.find((r) => r.task_id === selected) ?? list[0];

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Research"
        description="Each research step splits its questions into sub-questions, searches, quotes sources word for word, and stops when the questions are answered or nothing new turns up."
        actions={<ModeStatus />}
      >
        <AskBox projectId={projectId} onStarted={(id) => { setSelected(id); runs.reload(); }} />
      </Section>

      {runs.loading ? (
        <LoadingState label="Loading the research…" />
      ) : runs.error ? (
        <ErrorState error={runs.error} onRetry={runs.reload} />
      ) : list.length === 0 ? (
        <EmptyState title="No research yet">
          Research steps run after the plan is approved (the plan&apos;s research step), or ask a question above.
        </EmptyState>
      ) : (
        <>
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Research steps">
            {list.map((r) => (
              <li key={r.task_id}>
                <RunCard run={r} active={current?.task_id === r.task_id} onSelect={() => setSelected(r.task_id)} />
              </li>
            ))}
          </ul>
          {current && <Detail key={`${current.task_id}:${current.status}:${current.rounds}`} projectId={projectId} summary={current} developer={developer} />}
        </>
      )}
    </div>
  );
}

function ModeStatus() {
  const p = useApiQuery("research:providers", (signal) => getProviders(signal));
  if (!p.data) return null;
  return <Status tone={p.data.mode === "online" ? "progress" : "muted"} label={MODE_TEXT[p.data.mode] ?? p.data.mode} title={`Sources: ${p.data.providers.join(", ")}; ${p.data.corpus.pages} saved pages`} />;
}

function AskBox({ projectId, onStarted }: { projectId: string; onStarted: (taskId: string) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const questions = parseQuestions(text);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const { task_id } = await startResearch(projectId, questions);
      setText("");
      onStarted(task_id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="flex flex-col gap-2 sm:flex-row sm:items-start" onSubmit={(e) => { e.preventDefault(); if (questions.length) void submit(); }}>
      <label className="sr-only" htmlFor="research-question">Questions to research, one per line</label>
      <textarea id="research-question" rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask a question to research (one per line, up to 5)" className={cx(inputClass, "min-h-0 flex-1 resize-y")} />
      <Button type="submit" size="sm" busy={busy} disabled={!questions.length}>Research</Button>
      <InlineError error={error} />
    </form>
  );
}

function CoverageBar({ value, label }: { value: number; label: string }) {
  const tone = value >= 0.99 ? "bg-success" : value > 0 ? "bg-warning" : "bg-danger";
  return (
    <span className="flex items-center gap-2" title={label}>
      <span className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-line" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
        <span className={cx("block h-full rounded-full", tone)} style={{ width: `${Math.max(4, Math.round(value * 100))}%` }} />
      </span>
      <span className="text-xs tabular-nums text-fg-2">{percent(value)}</span>
    </span>
  );
}

function RunCard({ run, active, onSelect }: { run: RunSummary; active: boolean; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} aria-pressed={active} className={cx("flex w-full flex-col gap-1.5 rounded-md border px-3 py-2.5 text-left", active ? "border-accent bg-selected" : "border-line bg-surface hover:bg-hover")}>
      <span className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 text-sm font-semibold text-fg">{run.questions[0] ?? "Research"}</span>
        {run.status === "running" ? <Spinner className="size-3 shrink-0" label="researching" /> : <Badge>{run.claims} findings</Badge>}
      </span>
      {run.questions.length > 1 && <span className="text-xs text-muted">+ {run.questions.length - 1} more question{run.questions.length > 2 ? "s" : ""}</span>}
      <CoverageBar value={run.coverage} label={`${run.covered} of ${run.sub_questions} sub-questions answered`} />
      <span className="text-xs text-fg-2">{run.status === "running" ? `Round ${run.rounds}…` : stopText(run.stop_reason)}</span>
    </button>
  );
}

function Detail({ projectId, summary, developer }: { projectId: string; summary: RunSummary; developer: boolean }) {
  const run = useApiQuery(`research:run:${projectId}:${summary.task_id}:${summary.status}:${summary.rounds}`, (signal) => getRun(projectId, summary.task_id, signal));
  const [picked, setPicked] = useState<string[] | null>(null);
  if (run.loading) return <LoadingState label="Loading the research step…" />;
  if (run.error) return <ErrorState error={run.error} onRetry={run.reload} />;
  const d = run.data;
  if (!d) return null;
  const r = d.report;
  if (!r) {
    return (
      <Section title="Researching…" description={`Round ${d.trace.rounds.length}: ${d.trace.rounds.reduce((n, x) => n + x.fetched, 0)} sources read so far.`}>
        <Rounds detail={d} developer={developer} />
      </Section>
    );
  }
  const evidence = picked ? evidenceFor(r, picked) : [];
  return (
    <div className="flex flex-col gap-6">
      <Section title="Findings" description={stopText(r.stop_reason)} actions={<span className="text-xs text-muted">{summary.finished_at ? formatDateTime(summary.finished_at) : null}</span>}>
        <Findings report={r} onPick={setPicked} picked={picked} />
      </Section>
      {evidence.length > 0 && <EvidenceViewer key={evidence.map((e) => e.id).join(",")} projectId={projectId} taskId={summary.task_id} quotes={evidence} number={sourceNumbers(r).get(evidence[0]!.url) ?? 0} onClose={() => setPicked(null)} />}
      <Section title={`Sources (${r.sources.length})`} description="Each source's score: how relevant the passage was, how trustworthy the site is, how recent (only when it matters) and how much new information it added.">
        <Sources report={r} developer={developer} />
      </Section>
      <Section title="How it searched" description={`${d.trace.rounds.length} round${d.trace.rounds.length === 1 ? "" : "s"} · ${MODE_TEXT[d.trace.mode] ?? d.trace.mode}${developer ? ` · ${d.trace.tokens.toLocaleString()} tokens · ${d.trace.model_calls} model calls · ${d.trace.seconds.toFixed(1)} s` : ""}`}>
        <Rounds detail={d} developer={developer} />
      </Section>
      {r.summary_markdown && (
        <details className="rounded-md border border-line bg-surface px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-fg">The written report</summary>
          <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-xs leading-relaxed text-fg-2">{r.summary_markdown}</pre>
        </details>
      )}
    </div>
  );
}

function Findings({ report, onPick, picked }: { report: Report; onPick: (ids: string[]) => void; picked: string[] | null }) {
  const groups = useMemo(() => groupByQuestion(report), [report]);
  const bySub = useMemo(() => claimsBySub(report), [report]);
  const numbers = useMemo(() => sourceNumbers(report), [report]);
  return (
    <div className="flex flex-col gap-5">
      {groups.map((g, qi) => (
        <div key={qi} className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-fg">{g.question}</h3>
          {g.subs.map((s) => (
            <SubBlock key={s.id} sub={s} claims={bySub.get(s.id) ?? []} report={report} numbers={numbers} onPick={onPick} picked={picked} />
          ))}
        </div>
      ))}
    </div>
  );
}

function SubBlock({ sub, claims, report, numbers, onPick, picked }: { sub: SubQuestion; claims: Report["claims"]; report: Report; numbers: Map<string, number>; onPick: (ids: string[]) => void; picked: string[] | null }) {
  const st = STATUS_TEXT[sub.status];
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 text-sm text-fg">{sub.text}</span>
        <span className="flex items-center gap-2">
          <Status tone={st.tone} label={st.label} />
          <CoverageBar value={sub.coverage} label={`${sub.text}: ${percent(sub.coverage)} answered`} />
        </span>
      </div>
      {claims.length === 0 ? (
        <p className="mt-1.5 text-xs text-muted">No sourced answer found.</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1.5">
          {claims.map((c) => (
            <li key={c.id} className="text-sm text-fg-2">
              {c.text}{" "}
              {bySource(evidenceFor(report, c.evidence_ids)).map((group) => {
                const ids = group.map((e) => e.id);
                const on = picked !== null && picked.join() === ids.join();
                return (
                  <button key={ids.join()} type="button" onClick={() => onPick(ids)} aria-pressed={on} title={`Show the quote${ids.length > 1 ? "s" : ""} from ${host(group[0]!.url)}`} className={cx("ml-0.5 rounded px-1 align-baseline text-xs font-medium", on ? "bg-accent text-on-accent" : "bg-accent-soft text-accent hover:underline")}>
                    [{numbers.get(group[0]!.url) ?? "?"}]
                  </button>
                );
              })}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EvidenceViewer({ projectId, taskId, quotes, number, onClose }: { projectId: string; taskId: string; quotes: Evidence[]; number: number; onClose: () => void }) {
  const first = quotes[0]!;
  const ref = first.page_artifact;
  const page = useApiQuery(`research:page:${projectId}:${ref?.artifact_id ?? "-"}:${taskId}`, (signal) => (ref ? getPage(projectId, ref.artifact_id, taskId, signal) : Promise.resolve(null)));
  const href = safeHref(first.url);
  return (
    <section aria-label="Evidence" className="rounded-md border border-accent bg-surface px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-muted">Source [{number}] · {host(first.url)}</p>
          <p className="mt-0.5 break-words text-sm font-medium text-fg">{page.data?.title || first.url}</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
      </div>
      {quotes.map((q) => {
        const span = page.data?.spans.find((s) => s.evidence_id === q.id);
        return (
          <div key={q.id} className="mt-3">
            <blockquote className="border-l-2 border-accent pl-3 text-sm italic text-fg">{q.quote}</blockquote>
            {page.data && span ? (
              <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-fg-2">
                {(() => {
                  const ex = excerpt(page.data.text, span.start, span.end);
                  return (
                    <>
                      {ex.cutStart && "… "}
                      {ex.before}
                      <mark className="rounded bg-warning-soft px-0.5 text-fg">{ex.mark}</mark>
                      {ex.after}
                      {ex.cutEnd && " …"}
                    </>
                  );
                })()}
              </p>
            ) : null}
          </div>
        );
      })}
      {page.loading && <LoadingState label="Loading the saved page…" />}
      <p className="mt-2 text-xs text-muted">
        Checked word for word against the saved page{page.data ? <> (sha256 <Mono>{page.data.content_sha256.slice(0, 12)}</Mono>)</> : null}.
        {page.data?.license ? ` Licence: ${page.data.license}.` : ""}{" "}
        {href && <a href={href} target="_blank" rel="noreferrer noopener" className="text-accent hover:underline">Open the original</a>}
      </p>
    </section>
  );
}

function Sources({ report, developer }: { report: Report; developer: boolean }) {
  const numbers = sourceNumbers(report);
  const sorted = [...report.sources].sort((a, b) => (numbers.get(a.url) ?? 99) - (numbers.get(b.url) ?? 99));
  return (
    <ol className="flex flex-col gap-2">
      {sorted.map((s) => {
        const href = safeHref(s.url);
        return (
          <li key={s.url} className="flex flex-col gap-1 rounded-md border border-line bg-surface px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
            <span className="min-w-0">
              <span className="mr-1.5 text-xs font-semibold text-muted">[{numbers.get(s.url)}]</span>
              {href ? <a href={href} target="_blank" rel="noreferrer noopener" className="break-words text-sm text-fg hover:underline">{s.title || s.url}</a> : <span className="text-sm text-fg">{s.title || s.url}</span>}
              <span className="block text-xs text-muted">{host(s.url)} · {KIND_TEXT[s.kind ?? "web"] ?? s.kind}{developer && s.provider ? ` · via ${s.provider}` : ""}</span>
            </span>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-2">
              {s.score !== null && <span className="font-medium text-fg">score {percent(s.score)}</span>}
              {scoreParts(s).map((p) => (
                <span key={p.label}>{p.label} {percent(p.value)}</span>
              ))}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function Rounds({ detail, developer }: { detail: RunDetail; developer: boolean }) {
  const t = detail.trace;
  return (
    <div className="flex flex-col gap-2">
      {t.rounds.map((r) => (
        <details key={r.index} className="rounded-md border border-line bg-surface px-3 py-2" open={t.rounds.length === 1}>
          <summary className="cursor-pointer text-sm text-fg">
            Round {r.index}: {r.queries.length} searches, {r.hits} results, {r.fetched} pages read, {r.new_evidence} new quotes
            {r.quotes_dropped > 0 && <span className="text-warning"> · {r.quotes_dropped} refused (not word for word)</span>}
          </summary>
          <ul className="mt-2 flex flex-col gap-1 text-xs text-fg-2">
            {r.queries.map((q, i) => (
              <li key={i}>
                <Mono>{q.sub_question}</Mono> {q.provider}: “{q.query}” → {q.hits}
              </li>
            ))}
          </ul>
          {developer && Object.keys(r.fetch_failures).length > 0 && (
            <p className="mt-1 text-xs text-muted">Not read: {Object.entries(r.fetch_failures).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ")}</p>
          )}
        </details>
      ))}
      {developer && t.notes.length > 0 && <p className="text-xs text-warning">{t.notes.join(" · ")}</p>}
      {developer && t.claims_dropped.length > 0 && (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer">Findings refused by the citation check ({t.claims_dropped.length})</summary>
          <ul className="mt-1 list-disc pl-5">{t.claims_dropped.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
