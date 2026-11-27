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
  PageHeader,
  Section,
  Status,
  Table,
  td,
  th,
} from "@/components/ui";
import type { FeaturePageProps } from "@/lib/features";
import { formatRelative } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

import { getBench, getFineTune, getHardware, getRegistry, getRoutes, pullModel, setModelFlag, syncRegistry } from "./client";
import { FIT_LABEL, STATUS_TONE, SUITES, barWidth, gb, isCloud, memoryUsed, outcome, pct, quickResults } from "./logic";
import type { ModelRow, QuickResult } from "./types";

const ROUTES_POLL_MS = 2_000;
const SLOW_POLL_MS = 15_000;

/** Page "Models" (Member 11, Sprint 11): which models this machine has and can fit, which model answered each call
 * and why (the router's decisions, live), and the benchmark that the router's choices rest on. */
export function ModelsPage(props: FeaturePageProps) {
  void props.route;
  const registry = useApiQuery("models:registry", (s) => getRegistry(s), { intervalMs: SLOW_POLL_MS });
  const routes = useApiQuery("models:routes", (s) => getRoutes(s), { intervalMs: ROUTES_POLL_MS });
  const hardware = useApiQuery("models:hardware", (s) => getHardware(s), { intervalMs: SLOW_POLL_MS });
  const bench = useApiQuery("models:bench", (s) => getBench(s));
  const finetune = useApiQuery("models:finetune", (s) => getFineTune(s));
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [pullNote, setPullNote] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      registry.reload();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
    }
  }

  const enabled = routes.data?.enabled;
  return (
    <>
      <PageHeader
        title="Models"
        subtitle="Which model answers each request and why, what fits on this machine, and how the models compare on our own tasks."
        actions={
          <span className="flex flex-wrap items-center gap-3">
            {enabled !== undefined && (
              <Status tone={enabled ? "success" : "muted"} label={enabled ? "Router on" : "Router off (role maps)"} />
            )}
            {registry.data && registry.data.ollama_up !== null && (
              <Status tone={registry.data.ollama_up ? "success" : "muted"} label={registry.data.ollama_up ? "Ollama running" : "Ollama not running"} />
            )}
            <Button onClick={() => act(syncRegistry)} disabled={busy}>Refresh models</Button>
          </span>
        }
      />
      <div className="flex flex-col gap-8">
        {actionError != null && <InlineError error={actionError} />}

        <Section
          title="Route decisions"
          description="Every model call the router decided, newest first: what it would try, in which order, and who answered. Updates every 2 seconds."
        >
          {routes.loading ? (
            <LoadingState />
          ) : routes.error ? (
            <ErrorState error={routes.error} onRetry={routes.reload} />
          ) : !routes.data || routes.data.routes.length === 0 ? (
            <EmptyState title="No decisions yet">
              {enabled ? "Start a project: each model call appears here." : "The router is off (HMAP_ROUTER=off): the role maps decide and nothing is logged."}
            </EmptyState>
          ) : (
            <>
              <p className="mb-3 text-sm text-fg-2">
                {routes.data.summary.decisions} decisions ·{" "}
                {Object.entries(routes.data.summary.answered_by).map(([p, n]) => `${n} by ${p}`).join(", ") || "none answered yet"} ·{" "}
                {routes.data.summary.rate_limited} rate-limited attempts · {routes.data.summary.failed} failed
              </p>
              <Table label="Route decisions" minWidth="56rem">
                <thead>
                  <tr>
                    <th className={th}>When</th>
                    <th className={th}>Step / role</th>
                    <th className={th}>Tried in order</th>
                    <th className={th}>Outcome</th>
                    <th className={th}>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {routes.data.routes.map((r) => {
                    const o = outcome(r);
                    return (
                      <tr key={r.id}>
                        <td className={td}>{formatRelative(r.at)}</td>
                        <td className={td}>
                          {r.plugin} <Badge>{r.decision.role}</Badge>
                        </td>
                        <td className={td}>
                          <Mono>{r.chain.join(" → ")}</Mono>
                        </td>
                        <td className={td}>
                          <Status tone={o.tone} label={o.label} />
                          {r.attempts > 1 && <div className="text-xs text-muted">{r.attempts} attempts, {r.rate_limited} rate-limited</div>}
                        </td>
                        <td className={td}>
                          <span className="text-xs text-fg-2">{r.decision.reason}</span> <Badge>{r.rule}</Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            </>
          )}
        </Section>

        <Section title="Models" description="Local models (Ollama, MLX, llama.cpp) and the cloud routes of the team key pool. A disabled model is never used; pinned models are the release set.">
          {registry.loading ? (
            <LoadingState />
          ) : registry.error ? (
            <ErrorState error={registry.error} onRetry={registry.reload} />
          ) : (
            <>
              {registry.data?.error && <p className="mb-2 text-sm text-muted">{registry.data.error}: showing the models saved on disk.</p>}
              <Table label="Models" minWidth="52rem">
                <thead>
                  <tr>
                    <th className={th}>Model</th>
                    <th className={th}>Where</th>
                    <th className={th}>State</th>
                    <th className={th}>Size / loaded</th>
                    <th className={th}>Speed</th>
                    <th className={th}>Roles</th>
                    <th className={th}><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {(registry.data?.models ?? []).map((m: ModelRow) => (
                    <tr key={m.spec.id}>
                      <td className={td}>
                        <Mono>{m.spec.id}</Mono> {m.pinned && <Badge title="pinned for the release">pinned</Badge>}
                        {m.spec.quant && <div className="text-xs text-muted">{m.spec.quant}{m.spec.params_b ? ` · ${m.spec.params_b} B parameters` : ""}</div>}
                      </td>
                      <td className={td}>{m.spec.backend}</td>
                      <td className={td}>
                        <Status tone={STATUS_TONE[m.spec.status]} label={m.spec.status} />
                      </td>
                      <td className={td}>
                        {gb(m.spec.mem_gb)}
                        {m.resident_gb != null && <div className="text-xs text-success">loaded ({gb(m.resident_gb)})</div>}
                      </td>
                      <td className={td}>{m.spec.tok_s != null ? `${m.spec.tok_s} tok/s` : "–"}</td>
                      <td className={td}>{m.spec.roles_ok.join(", ") || "–"}</td>
                      <td className={td}>
                        <span className="flex gap-2">
                          {!m.pinned && (
                            <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => setModelFlag(m.spec.id, "pin"))}>Pin</Button>
                          )}
                          {m.spec.status === "disabled" ? (
                            <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => setModelFlag(m.spec.id, "enable"))}>Enable</Button>
                          ) : (
                            <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => setModelFlag(m.spec.id, "disable"))}>Disable</Button>
                          )}
                          {m.spec.status === "missing" && !isCloud(m.spec.id) && (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy}
                              onClick={() => act(async () => {
                                const r = await pullModel(m.spec.id);
                                setPullNote(r.started ? `Pulling ${m.spec.id}…` : `${r.why ?? ""}: ${r.command}`);
                              })}
                            >
                              How to get it
                            </Button>
                          )}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              {pullNote && <p className="mt-2 text-sm text-fg-2"><Mono>{pullNote}</Mono></p>}
            </>
          )}
        </Section>

        <Section title="This machine" description="Memory now, and which local models fit next to the running platform (weights + the cache for 8k tokens of context).">
          {hardware.loading ? (
            <LoadingState />
          ) : hardware.error ? (
            <ErrorState error={hardware.error} onRetry={hardware.reload} />
          ) : hardware.data ? (
            <div className="flex flex-col gap-4">
              <div>
                <p className="text-sm">
                  {hardware.data.hardware.chip || hardware.data.hardware.platform} · {gb(hardware.data.hardware.total_gb)} memory ·{" "}
                  {gb(memoryUsed(hardware.data.hardware))} in use · {gb(hardware.data.hardware.swap_used_gb)} swap · GPU {hardware.data.hardware.gpu}
                </p>
                <div className="mt-2 h-2 w-full max-w-xl rounded bg-surface-2" role="img" aria-label={`memory in use ${pct(memoryUsed(hardware.data.hardware) / hardware.data.hardware.total_gb)}`}>
                  <div className="h-2 rounded bg-accent" style={{ width: barWidth(memoryUsed(hardware.data.hardware) / hardware.data.hardware.total_gb) }} />
                </div>
                {hardware.data.hardware.notes.map((n) => (
                  <p key={n} className="mt-1 text-xs text-warning">{n}</p>
                ))}
              </div>
              <Table label="Fits on this machine" minWidth="36rem">
                <thead>
                  <tr>
                    <th className={th}>Model</th>
                    <th className={th}>Needs</th>
                    <th className={th}>Here</th>
                    <th className={th}>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {hardware.data.feasibility.map((f) => (
                    <tr key={f.model}>
                      <td className={td}><Mono>{f.model}</Mono></td>
                      <td className={td}>{gb(f.need_gb)}</td>
                      <td className={td}><Status tone={FIT_LABEL[f.fit].tone} label={FIT_LABEL[f.fit].label} /></td>
                      <td className={td}><span className="text-xs text-fg-2">{f.why}</span></td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <p className="text-xs text-muted">
                Laptop sizes (computed, not measured):{" "}
                {hardware.data.sizing.map((s) => `${s.ram_gb} GB → ${s.fits.length ? s.fits.join(", ") : "replay only"}`).join(" · ")}
              </p>
            </div>
          ) : null}
        </Section>

        <Section title="Benchmark" description="Each model on the same 88 tasks from our own work (extraction, planning, critique, claim checking, coding), scored by code. The router orders the cloud routes by these numbers only when the difference is clear.">
          {bench.loading ? (
            <LoadingState />
          ) : bench.error ? (
            <ErrorState error={bench.error} onRetry={bench.reload} />
          ) : (
            <QuickTable results={quickResults(bench.data?.files ?? {})} />
          )}
        </Section>

        <Section title="Fine-tune experiment" description="A small local model trained on the cloud judge's answers to Member 6's claim checks, compared with the same model untrained on claims it never saw.">
          {finetune.loading ? <LoadingState /> : <FineTuneResult files={finetune.data?.files ?? {}} />}
        </Section>
      </div>
    </>
  );
}

function QuickTable({ results }: { results: QuickResult[] }) {
  if (results.length === 0) return <EmptyState title="No benchmark results yet">Run the benchmark (docs/members/11/eval.md).</EmptyState>;
  return (
    <Table label="Benchmark results" minWidth="52rem">
      <thead>
        <tr>
          <th className={th}>Model</th>
          <th className={th}>Overall</th>
          {SUITES.map((s) => (
            <th key={s} className={th}>{s}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <tr key={r.model}>
            <td className={td}>
              <Mono>{r.model}</Mono> <Badge>{isCloud(r.model) ? "cloud" : "local"}</Badge>
            </td>
            <td className={td}>
              <strong>{r.quality == null ? "–" : r.quality.toFixed(3)}</strong>
              {r.coverage < 1 && <div className="text-xs text-muted">partial ({pct(r.coverage)} of the weight)</div>}
            </td>
            {SUITES.map((s) => {
              const v = r.suites[s];
              return (
                <td key={s} className={td}>
                  {v?.score == null ? (
                    <span className="text-muted">{v ? `not answered (${v.answered}/${v.items})` : "–"}</span>
                  ) : (
                    <>
                      <span>{v.score.toFixed(2)}</span>
                      <div className="mt-1 h-1.5 w-16 rounded bg-surface-2" aria-hidden="true">
                        <div className="h-1.5 rounded bg-accent" style={{ width: barWidth(v.score) }} />
                      </div>
                      {v.answered < v.items && <div className="text-xs text-muted">{v.answered}/{v.items} answered</div>}
                    </>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function FineTuneResult({ files }: { files: Record<string, unknown> }) {
  const res = files["eval_result"] as
    | { verdict: string; base: { heldout_m6: { accuracy: number; n: number } }; lora: { heldout_m6: { accuracy: number } } }
    | undefined;
  if (!res) return <EmptyState title="Not evaluated yet">The training and its evaluation have not run on this machine yet.</EmptyState>;
  return (
    <p className="text-sm">
      Held-out claim checks ({res.base.heldout_m6.n}): untrained {pct(res.base.heldout_m6.accuracy)} → trained {pct(res.lora.heldout_m6.accuracy)}. <span className="text-fg-2">{res.verdict}</span>
    </p>
  );
}
