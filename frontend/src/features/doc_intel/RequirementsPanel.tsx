"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
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
import { usePreferences } from "@/lib/preferences";
import { useApiQuery } from "@/lib/useApiQuery";

import { getDocumentModel, getRequirements, saveRequirements } from "./client";
import {
  CONSTRAINT_LABEL,
  PRIORITY_LABEL,
  addRequirement,
  confidenceLevel,
  confirmAll,
  confirmRequirement,
  editedBy,
  groupByFolder,
  marksSummary,
  removeRequirement,
  sameSet,
  unconfirmedCount,
  updateRequirement,
} from "./logic";
import { SourceView } from "./SourceView";
import type { Priority, Requirement, RequirementSet, SourceRef } from "./types";

const ACTIVE = new Set(["CREATED", "READY", "ASSIGNED", "RUNNING", "RETRY_WAIT", "AWAITING_REVIEW"]);

interface Selected {
  ref: SourceRef | null;
  label: string;
}

/** Project tab "Requirements": what the Analyst found in the uploaded documents, with sources, edits and versions. */
export function RequirementsPanel({ projectId, tasks, events }: ProjectPanelProps) {
  const { developer } = usePreferences();
  const extract = useMemo(
    () => [...tasks].filter((t) => t.capability === "document.extract").sort((a, b) => a.updated_at.localeCompare(b.updated_at)).at(-1),
    [tasks],
  );
  const [savedTick, setSavedTick] = useState(0);
  const key = `${projectId}:${extract?.task_id ?? "none"}:${extract?.state ?? ""}:${savedTick}`;
  const query = useApiQuery(key, (signal) => getRequirements(projectId, signal));
  const data = query.data;

  const [draft, setDraft] = useState<RequirementSet | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [newText, setNewText] = useState("");

  // a fresh extraction (or a saved edit) replaces the draft
  const loadedVersion = data ? `${data.artifact.artifact_id}@${data.artifact.version}` : null;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset local edits when the server copy changes
    setDraft(data ? data.requirement_set : null);
    setEditing(null);
  }, [loadedVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  const model = useApiQuery(selected || developer ? `${projectId}:model:${loadedVersion}` : null, (signal) =>
    getDocumentModel(projectId, signal),
  );

  const running = extract && ACTIVE.has(extract.state);
  const progress = useMemo(() => {
    if (!extract) return null;
    const p = [...events].reverse().find((e) => e.event_type === "task.progress" && e.aggregate_id === extract.task_id);
    return (p?.data?.summary as string | undefined) ?? null;
  }, [events, extract]);

  if (query.loading) return <LoadingState label="Loading requirements…" />;
  if (query.error) return <ErrorState error={query.error} onRetry={query.reload} />;
  if (!data || !draft) {
    if (running) {
      return (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <Spinner label="The Analyst is reading your documents…" />
          {progress && <p className="text-xs text-muted">{progress}</p>}
        </div>
      );
    }
    return (
      <EmptyState title="No requirements yet">
        Upload an assignment or brief, or type a request: the Analyst lists its requirements, constraints, deliverables
        and marking scheme here, each with the place it came from.
      </EmptyState>
    );
  }

  const rs = draft;
  const dirty = !sameSet(rs, data.requirement_set);
  const marks = marksSummary(rs);
  const groups = groupByFolder(rs.requirements);

  async function save() {
    if (!data) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveRequirements(projectId, data.artifact.artifact_id, data.artifact.version, rs);
      setSavedTick((n) => n + 1);
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  }

  function addOne(e: FormEvent) {
    e.preventDefault();
    if (!newText.trim()) return;
    setDraft(addRequirement(rs, newText));
    setNewText("");
  }

  const show = (ref: SourceRef | null, label: string) => setSelected({ ref, label });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-fg-2">
          <strong className="font-semibold text-fg">{rs.requirements.length}</strong> requirements ·{" "}
          {rs.constraints.length} constraints · {rs.deliverables.length} deliverables · {rs.evaluation_criteria.length}{" "}
          marking criteria
          {marks.sum > 0 && (
            <>
              {" "}
              · {marks.sum} marks
              {marks.total !== null && !marks.consistent && <span className="text-danger"> (document says {marks.total})</span>}
            </>
          )}
        </p>
        <p className="text-xs text-muted">
          Version {data.artifact.version}, {editedBy(data.artifact.created_by)} {formatRelative(data.artifact.created_at)}
        </p>
      </div>

      {running && (
        <p className="text-xs text-muted">
          <Spinner className="mr-1 inline size-3" /> A new extraction is running{progress ? `: ${progress}` : "…"}
        </p>
      )}

      {dirty && (
        <div role="region" aria-label="Unsaved changes" className="flex flex-wrap items-center gap-3 border-l-2 border-accent bg-surface-2 px-4 py-3">
          <p className="min-w-0 flex-1 text-sm text-fg">You have unsaved changes. Saving keeps the old version in the history.</p>
          <Button variant="ghost" onClick={() => setDraft(data.requirement_set)} disabled={saving}>
            Discard
          </Button>
          <Button variant="primary" onClick={save} busy={saving}>
            Save as version {data.artifact.version + 1}
          </Button>
          <div className="basis-full">
            <InlineError error={saveError} />
          </div>
        </div>
      )}

      {rs.open_questions.length > 0 && (
        <Section title="Questions to check" description="Things the Analyst was unsure about. Answer them by editing the list below.">
          <ul className="space-y-1.5 text-sm text-fg-2">
            {rs.open_questions.map((q) => (
              <li key={q} className="flex gap-2">
                <span aria-hidden="true" className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warning" />
                {q}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className={cx("grid gap-6", selected && "lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]")}>
        <div className="min-w-0 space-y-6">
          <Section
            title="Requirements"
            description="What the finished work must do or be. Confirm the ones you have checked."
            actions={
              unconfirmedCount(rs) > 0 && (
                <Button size="sm" variant="ghost" onClick={() => setDraft(confirmAll(rs))}>
                  Confirm all {unconfirmedCount(rs)}
                </Button>
              )
            }
          >
            {groups.map((g) => (
              <div key={g.folder ?? "-"} className="mb-4 last:mb-0">
                {g.folder && <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">{g.folder}</h3>}
                <ul className="divide-y divide-line">
                  {g.items.map((r) => (
                    <RequirementRow
                      key={r.id}
                      req={r}
                      developer={developer}
                      editing={editing === r.id}
                      selected={selected?.ref === r.source_ref}
                      onEdit={() => setEditing(editing === r.id ? null : r.id)}
                      onChange={(patch) => setDraft(updateRequirement(rs, r.id, patch))}
                      onRemove={() => setDraft(removeRequirement(rs, r.id))}
                      onConfirm={() => setDraft(confirmRequirement(rs, r.id))}
                      onSource={() => show(r.source_ref, r.id)}
                    />
                  ))}
                </ul>
              </div>
            ))}
            <form onSubmit={addOne} className="mt-3 flex flex-col gap-2 sm:flex-row">
              <label htmlFor="new-requirement" className="sr-only">
                New requirement
              </label>
              <input
                id="new-requirement"
                className={inputClass}
                value={newText}
                maxLength={1000}
                placeholder="Add a requirement the documents missed"
                onChange={(e) => setNewText(e.target.value)}
              />
              <Button type="submit" disabled={!newText.trim()}>
                Add
              </Button>
            </form>
          </Section>

          {rs.constraints.length > 0 && (
            <Section title="Constraints" description="Rules about how the work is done.">
              <ul className="divide-y divide-line">
                {rs.constraints.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5 text-sm">
                    <Mono className="pt-0.5">{c.id}</Mono>
                    <span className="min-w-0 flex-1 text-fg">{c.text}</span>
                    <Badge>{CONSTRAINT_LABEL[c.kind] ?? c.kind}</Badge>
                    {c.source_ref && (
                      <Button size="sm" variant="ghost" onClick={() => show(c.source_ref, c.id)}>
                        Source
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {rs.deliverables.length > 0 && (
            <Section title="Deliverables" description="What to hand in.">
              <ul className="divide-y divide-line">
                {rs.deliverables.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5 text-sm">
                    <Mono className="pt-0.5">{d.id}</Mono>
                    <span className="min-w-0 flex-1 text-fg">{d.name}</span>
                    {d.format && <Badge>{d.format}</Badge>}
                    {d.source_ref && (
                      <Button size="sm" variant="ghost" onClick={() => show(d.source_ref, d.id)}>
                        Source
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {rs.evaluation_criteria.length > 0 && (
            <Section
              title="Marking scheme"
              description={marks.total !== null ? `${marks.sum} of ${marks.total} marks${marks.consistent ? ", adds up" : ""}` : `${marks.sum} marks`}
            >
              <Table label="Marking criteria" minWidth="32rem">
                <thead>
                  <tr>
                    <th className={th}>Criterion</th>
                    <th className={cx(th, "text-right")}>Marks</th>
                    <th className={th}>Levels</th>
                    <th className={th}>
                      <span className="sr-only">Source</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rs.evaluation_criteria.map((e) => (
                    <tr key={e.id}>
                      <td className={td}>
                        {developer && <Mono className="mr-2">{e.id}</Mono>}
                        {e.criterion}
                      </td>
                      <td className={cx(td, "text-right tabular-nums")}>{e.max_marks}</td>
                      <td className={cx(td, "text-xs text-fg-2")}>
                        {e.rubric_levels.length === 0
                          ? "—"
                          : e.rubric_levels.map((l) => `${l.label}${l.marks !== null ? ` (${l.marks})` : ""}`).join(" · ")}
                      </td>
                      <td className={cx(td, "text-right")}>
                        {e.source_ref && (
                          <Button size="sm" variant="ghost" onClick={() => show(e.source_ref, e.id)}>
                            Source
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Section>
          )}

          {developer && (
            <Section title="Raw data">
              <JsonBlock value={rs} summary="RequirementSet JSON" />
              <p className="mt-2 text-xs text-muted">
                Artifact <Mono>{data.artifact.artifact_id}</Mono> · {data.versions.length} version{data.versions.length === 1 ? "" : "s"}
              </p>
              {model.data?.extraction && (
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-fg-2">
                  <dt className="text-muted">Answered by</dt>
                  <dd>
                    {Object.entries(model.data.extraction.answered_by)
                      .map(([who, n]) => `${who} (${n} part${n === 1 ? "" : "s"})`)
                      .join(", ") || "no model (keyword rules only)"}
                  </dd>
                  <dt className="text-muted">Parts</dt>
                  <dd>
                    {model.data.extraction.llm_chunks} of {model.data.extraction.chunks} by the model
                    {model.data.extraction.rules_only_chunks > 0 && `, ${model.data.extraction.rules_only_chunks} by rules only`} · prompt v
                    {model.data.extraction.prompt_version}
                  </dd>
                  <dt className="text-muted">Quotes</dt>
                  <dd>{Object.entries(model.data.extraction.quotes).map(([k, n]) => `${n} ${k}`).join(", ")}</dd>
                  {Object.keys(model.data.extraction.ocr_pages).length > 0 && (
                    <>
                      <dt className="text-muted">OCR</dt>
                      <dd>{Object.entries(model.data.extraction.ocr_pages).map(([k, n]) => `${n} page${n === 1 ? "" : "s"} by ${k}`).join(", ")}</dd>
                    </>
                  )}
                </dl>
              )}
            </Section>
          )}
        </div>

        {selected && (
          <aside aria-label="Source" className="min-w-0 lg:sticky lg:top-4 lg:self-start">
            <SourceView
              projectId={projectId}
              model={model.data}
              loading={model.loading}
              error={model.error}
              onRetry={model.reload}
              sourceRef={selected.ref}
              label={selected.label}
              onClose={() => setSelected(null)}
            />
          </aside>
        )}
      </div>
    </div>
  );
}

function RequirementRow({
  req,
  developer,
  editing,
  selected,
  onEdit,
  onChange,
  onRemove,
  onConfirm,
  onSource,
}: {
  req: Requirement;
  developer: boolean;
  editing: boolean;
  selected: boolean;
  onEdit: () => void;
  onChange: (patch: Partial<Requirement>) => void;
  onRemove: () => void;
  onConfirm: () => void;
  onSource: () => void;
}) {
  const conf = confidenceLevel(req.confidence);
  const fieldId = `req-${req.id}`;
  return (
    <li className={cx("py-3", selected && "bg-surface-2")}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <Mono className="pt-0.5">{req.id}</Mono>
        <div className="min-w-0 flex-1">
          {editing ? (
            <>
              <label htmlFor={fieldId} className="sr-only">
                Requirement {req.id}
              </label>
              <textarea
                id={fieldId}
                className={cx(textareaClass, "min-h-16")}
                value={req.text}
                onChange={(e) => onChange({ text: e.target.value })}
              />
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
                <label className="flex items-center gap-1.5">
                  Priority
                  <select
                    className="rounded-[4px] border border-line-strong bg-surface px-2 py-1"
                    value={req.priority}
                    onChange={(e) => onChange({ priority: e.target.value as Priority })}
                  >
                    {(["must", "should", "could"] as const).map((p) => (
                      <option key={p} value={p}>
                        {PRIORITY_LABEL[p]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={req.type === "non_functional"}
                    onChange={(e) => onChange({ type: e.target.checked ? "non_functional" : "functional" })}
                  />
                  Quality requirement
                </label>
              </div>
            </>
          ) : (
            <p className="text-sm text-fg">{req.text}</p>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge className={req.priority === "must" ? "bg-accent-soft text-accent-ink" : undefined}>{PRIORITY_LABEL[req.priority]}</Badge>
            {req.type === "non_functional" && <Badge>Quality</Badge>}
            {(developer || req.confidence < 0.85 || req.confidence >= 1) && (
              <Status tone={conf.tone} label={developer ? `${conf.label} (${req.confidence.toFixed(2)})` : conf.label} />
            )}
          </div>
        </div>
        <div className="flex gap-1">
          {req.confidence < 1 && (
            <Button size="sm" variant="ghost" onClick={onConfirm} aria-label={`Confirm ${req.id}`}>
              Confirm
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onSource} aria-pressed={selected}>
            Source
          </Button>
          <Button size="sm" variant="ghost" onClick={onEdit} aria-expanded={editing} aria-controls={fieldId}>
            {editing ? "Done" : "Edit"}
          </Button>
          <Button size="sm" variant="quiet-danger" onClick={onRemove} aria-label={`Remove ${req.id}`}>
            Remove
          </Button>
        </div>
      </div>
    </li>
  );
}
