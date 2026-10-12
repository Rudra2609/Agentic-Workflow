"use client";

/** The signed-in user's workspace: start a project in plain words, then find and reopen projects. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDeferredValue, useId, useMemo, useState, type FormEvent } from "react";

import { useWorkspace } from "@/components/AppShell";
import { DocumentDrop } from "@/components/DocumentDrop";
import { useToast } from "@/components/Toast";
import { Button, EmptyState, ErrorState, Field, InlineError, LoadingState, Status, cx, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { suggestName, withoutCommonRoot, type DocItem } from "@/lib/documents";
import { formatRelative } from "@/lib/format";
import { ACTIVE_PROJECT_STATES, NEEDS_ATTENTION_STATES, greeting, nameFromGoal, projectStateText } from "@/lib/plain";
import { usePreferences } from "@/lib/preferences";
import type { Project } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

const EXAMPLES = [
  "Create a website for my college chess club with tournament registration, player profiles and a leaderboard.",
  "Research five note-taking apps and prepare a report comparing their pricing and features.",
  "Write a multi-client TCP chat server in Python with tests and a short README.",
];

/** Shown while capabilities are served by placeholders, so nobody mistakes sample output for real AI work. */
export function StubNotice({ compact = false }: { compact?: boolean }) {
  const caps = useApiQuery("capabilities", (s) => api.listCapabilities(s), { intervalMs: 60_000 });
  const rows = caps.data ?? [];
  const stubs = rows.filter((r) => r.status !== "real");
  if (!rows.length || !stubs.length) return null;
  const all = stubs.length === rows.length;
  return (
    <p role="note" className={cx("hm-sticky max-w-3xl rounded-[2px] px-5 py-4 text-sm leading-relaxed", compact ? "" : "mb-12")}>
      <span className="font-medium">Test environment.</span>{" "}
      {all
        ? "Every member of your AI team is a placeholder: it shows how the workflow runs but does not do real AI work, so results are sample data."
        : `${stubs.length} of ${rows.length} team roles are placeholders that return sample data instead of real work.`}{" "}
      <Link href="/team" className="font-semibold text-sticky-ink underline underline-offset-2">
        See your AI team
      </Link>
    </p>
  );
}

function Composer() {
  const router = useRouter();
  const toast = useToast();
  const [source, setSource] = useState<"text" | "file">("text");
  const [goal, setGoal] = useState("");
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [name, setName] = useState("");
  const [auto, setAuto] = useState(false);
  const [local, setLocal] = useState(false);
  const usage = useApiQuery("llm-usage", (sig) => api.llmUsage(sig), { intervalMs: 300_000 });
  const cloudKeys = Object.keys(usage.data?.cloud_keys ?? {}).length;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const ids = { goal: useId(), file: useId(), name: useId(), mode: useId() };

  const suggestedName = source === "text" ? nameFromGoal(goal) : suggestName(docs);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (source === "text" && goal.trim().length < 10) {
      setFieldError("Describe the goal in a sentence or two (at least 10 characters).");
      return;
    }
    if (source === "file" && docs.length === 0) {
      setFieldError("Choose at least one document to upload.");
      return;
    }
    setFieldError(null);
    setBusy(true);
    try {
      const projectName = (name.trim() || suggestedName || "Untitled project").slice(0, 200);
      const project = await api.createProject(projectName, auto, source === "text" ? goal : undefined, !local);
      if (source === "file") await api.uploadDocuments(project.project_id, withoutCommonRoot(docs));
      toast("Project created. Your AI team is reading the request.");
      router.push(`/projects/${encodeURIComponent(project.project_id)}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate aria-labelledby="composer-title" className="mb-12">
      <h2 id="composer-title" className="text-xl font-semibold tracking-tight">
        What would you like your AI team to do?
      </h2>
      <p className="mt-1 mb-4 text-sm text-fg-2">
        Describe the outcome you want. You&apos;ll see the requirements and a step-by-step plan before work begins
        — unless you choose to run it automatically.
      </p>

      <div role="tablist" aria-label="How to describe the work" className="mb-2 inline-flex gap-4 text-sm">
        {(["text", "file"] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={source === s}
            onClick={() => {
              setSource(s);
              setFieldError(null);
            }}
            className={cx("border-b-2 pb-1", source === s ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg")}
          >
            {s === "text" ? "Describe it" : "Upload a document"}
          </button>
        ))}
      </div>

      <div className="hm-clipped rounded-[3px] focus-within:border-focus">
        <span aria-hidden="true" className="hm-clip" />
        {source === "text" ? (
          <>
            <label htmlFor={ids.goal} className="sr-only">
              Your goal
            </label>
            <textarea
              id={ids.goal}
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={4}
              maxLength={20000}
              placeholder="For example: Create a website for my college chess club with tournament registration and a leaderboard."
              aria-invalid={Boolean(fieldError)}
              aria-describedby={fieldError ? `${ids.goal}-error` : undefined}
              className="block w-full resize-y bg-transparent px-6 py-5 text-base leading-relaxed text-fg placeholder:text-muted focus:outline-none"
            />
          </>
        ) : (
          <div className="px-5 pt-6 pb-5 sm:px-6">
            <DocumentDrop
              id={ids.file}
              docs={docs}
              onChange={setDocs}
              onMessage={setFieldError}
              invalid={Boolean(fieldError)}
              describedBy={fieldError ? `${ids.goal}-error` : undefined}
            />
          </div>
        )}
        <div className="hm-perforated flex flex-wrap items-center gap-x-6 gap-y-3 px-6 py-4">
          <fieldset className="flex flex-wrap gap-x-5 gap-y-2" aria-describedby={`${ids.mode}-help`}>
            <legend className="sr-only">Execution mode</legend>
            {[
              { v: false, label: "Review the plan first", help: "Work pauses until you approve the plan." },
              { v: true, label: "Run automatically", help: "Work starts as soon as the plan is ready. You can still stop it." },
            ].map((o) => (
              <label key={String(o.v)} className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" name="mode" checked={auto === o.v} onChange={() => setAuto(o.v)} className="accent-[var(--hm-accent)]" />
                {o.label}
              </label>
            ))}
          </fieldset>
          <Button type="submit" variant="primary" busy={busy} className="ml-auto">
            {busy ? "Creating…" : "Create project"}
          </Button>
        </div>
      </div>
      <p id={`${ids.mode}-help`} className="mt-2 text-xs text-muted">
        {auto
          ? "Automatic: the plan is still shown and recorded, but nobody needs to approve it. The red Stop button halts everything at any time."
          : "Manual approval: after planning, the project waits for you to review and approve the plan."}
      </p>
      {fieldError && (
        <p id={`${ids.goal}-error`} className="mt-2 text-sm text-danger">
          {fieldError}
        </p>
      )}

      <div className="mt-10 grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Field
            label={<span className="text-base font-semibold">Project name (optional)</span>}
            htmlFor={ids.name}
            hint={suggestedName ? `Leave empty to use “${suggestedName}”.` : `Leave empty to name it after your ${source === "text" ? "goal" : "document"}.`}
          >
            {({ describedBy }) => (
              <input id={ids.name} className={cx(inputClass, "py-3 text-base")} value={name} onChange={(e) => setName(e.target.value)} maxLength={200} aria-describedby={describedBy} />
            )}
          </Field>
          <label className="flex cursor-pointer items-start gap-3">
            <input type="checkbox" checked={local} onChange={(e) => setLocal(e.target.checked)} aria-describedby={`${ids.name}-local`} className="mt-1 size-4 accent-[var(--hm-accent)]" />
            <span>
              <span className="block text-sm font-semibold text-fg">Keep this project on this computer</span>
              <span id={`${ids.name}-local`} className="mt-0.5 block text-xs text-muted">
                {cloudKeys
                  ? "No step uses a cloud model; everything runs on the local model. Use it for private documents. It is slower and less capable."
                  : "No cloud keys are set up right now, so everything already runs here. This keeps it that way if keys are added later."}
              </span>
            </span>
          </label>
        </div>
        <div>
          <p className="mb-1 text-base font-semibold text-fg">Examples</p>
          <p className="mb-3 text-xs text-muted">Pick one to put it in the box above.</p>
          <ul className="grid gap-4 sm:grid-cols-3">
            {EXAMPLES.map((ex) => (
              <li key={ex} className="hm-slip rounded-[3px]">
                <button
                  type="button"
                  onClick={() => {
                    setSource("text");
                    setGoal(ex);
                  }}
                  className="block h-full w-full px-4 py-3.5 text-left text-sm leading-relaxed text-fg-2 hover:text-accent-ink"
                >
                  {ex}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">Examples of requests, not promises: what the team can do depends on which agents are installed.</p>
        </div>
      </div>
      <div className="mt-2">
        <InlineError error={error} />
      </div>
    </form>
  );
}

type Filter = "all" | "active" | "attention" | "completed" | "stopped" | "archived";
const FILTERS: { id: Filter; label: string; match: (p: Project) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "active", label: "In progress", match: (p) => ACTIVE_PROJECT_STATES.has(p.state) },
  { id: "attention", label: "Needs attention", match: (p) => NEEDS_ATTENTION_STATES.has(p.state) },
  { id: "completed", label: "Completed", match: (p) => p.state === "COMPLETED" },
  { id: "stopped", label: "Stopped", match: (p) => p.state === "CANCELLED" },
  { id: "archived", label: "Archived", match: () => true },
];

function progressOf(p: Project): string | null {
  const counts = p.current_run_task_states ?? {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total || !ACTIVE_PROJECT_STATES.has(p.state)) return null;
  return `${counts.COMPLETED ?? 0} of ${total} tasks done`;
}

function ProjectList() {
  const { projects: live } = useWorkspace();
  const { developer } = usePreferences();
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim());
  const archived = useApiQuery(filter === "archived" ? `projects:archived:${query}` : null, (s) =>
    api.listProjects(s, { archived: true, q: query || undefined }),
  );
  const searched = useApiQuery(filter !== "archived" && query ? `projects:q:${query}` : null, (s) => api.listProjects(s, { q: query }));
  const source = filter === "archived" ? archived : query ? searched : live;
  const rule = FILTERS.find((f) => f.id === filter)!;
  const rows = useMemo(() => (source.data ?? []).filter(rule.match), [source.data, rule]);
  const searchId = useId();

  if (live.loading) return <LoadingState label="Loading your projects…" />;
  if (live.error) return <ErrorState error={live.error} onRetry={live.reload} />;
  const total = live.data?.length ?? 0;

  if (total === 0 && filter !== "archived") {
    return (
      <EmptyState title="Your workspace is ready.">
        Describe a goal above to create your first project. You can review the proposed plan before work begins.
      </EmptyState>
    );
  }

  return (
    <section aria-labelledby="projects-title">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id="projects-title" className="text-xl font-semibold tracking-tight">
          Projects
        </h2>
        <label htmlFor={searchId} className="sr-only">
          Search projects
        </label>
        <input id={searchId} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search projects" maxLength={200} className={cx(inputClass, "h-9 !w-64 max-w-full py-1")} />
      </div>
      <div role="tablist" aria-label="Filter projects" className="mb-2 flex flex-wrap gap-1 border-b border-line pb-3">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            role="tab"
            aria-selected={filter === f.id}
            onClick={() => setFilter(f.id)}
            className={cx("rounded-lg px-2.5 py-1 text-sm", filter === f.id ? "bg-selected font-medium text-fg" : "text-muted hover:bg-hover hover:text-fg")}
          >
            {f.label}
          </button>
        ))}
      </div>
      {source.loading ? (
        <LoadingState label="Searching…" />
      ) : source.error ? (
        <ErrorState error={source.error} onRetry={source.reload} />
      ) : rows.length === 0 ? (
        <EmptyState title={filter === "archived" ? "No archived projects" : "No projects match"}>
          {filter === "archived" ? "Projects you archive appear here." : "Try another filter or search."}
        </EmptyState>
      ) : (
        <ul className="hm-tray space-y-3 p-3 sm:p-4">
          {rows.map((p) => {
            const st = projectStateText(p.state);
            const progress = progressOf(p);
            return (
              <li key={p.project_id} className="hm-slip rounded-[3px]">
                <Link href={`/projects/${encodeURIComponent(p.project_id)}`} className="group grid gap-x-6 gap-y-1 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_11rem_7rem]">
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-fg group-hover:text-accent-ink">{p.name}</span>
                    <span className="block truncate text-xs text-muted">
                      {p.description || (p.runs?.at(-1)?.documents.join(", ") ?? "") || "No request yet"}
                    </span>
                    {developer && <span className="block font-mono text-2xs text-muted">{p.project_id}</span>}
                  </span>
                  <span className="flex flex-col justify-center gap-0.5">
                    <Status tone={st.tone} label={st.label} live={ACTIVE_PROJECT_STATES.has(p.state) && p.state !== "AWAITING_APPROVAL"} />
                    {progress && <span className="text-xs text-muted italic">{progress}</span>}
                  </span>
                  <span className="self-center text-xs text-muted sm:text-right" title={p.last_activity_at}>
                    {formatRelative(p.last_activity_at ?? p.updated_at)}
                    {(p.runs?.length ?? 0) > 1 && <span className="block text-2xs">{p.runs!.length} runs</span>}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function WorkspaceView() {
  const { user } = useAuth();
  const first = user.name.split(/\s+/)[0] || user.name;
  return (
    <>
      <div className="mb-8">
        <h1 className="text-[2rem] leading-tight font-bold tracking-[-0.025em] sm:text-[2.5rem]">
          {greeting()}, {first}.
        </h1>
        <p className="mt-1.5 text-base text-fg-2">Continue your work or start something new.</p>
      </div>
      <StubNotice />
      <Composer />
      <ProjectList />
    </>
  );
}
