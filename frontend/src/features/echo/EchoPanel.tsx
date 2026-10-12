"use client";

import { useState, type FormEvent } from "react";

import { TaskStateChip } from "@/components/StateChip";
import { Button, EmptyState, InlineError, Mono, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { ProjectPanelProps } from "@/lib/features";
import { formatTime, shortId } from "@/lib/format";

/** Example project panel: lists this project's `echo` tasks and can create one (handy for a live smoke test). */
export function EchoPanel({ projectId, tasks, reload }: ProjectPanelProps) {
  const echoTasks = tasks.filter((t) => t.capability === "echo");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createTask(projectId, { capability: "echo", objective: text.trim() });
      setText("");
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-fg-2">
        Example feature panel from <Mono>src/features/echo/</Mono>. The <Mono>echo</Mono> agent copies the objective
        into a result artifact.
      </p>
      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <label htmlFor="echo-objective" className="mb-1 block text-sm font-medium">
            Echo text
          </label>
          <input
            id="echo-objective"
            className={inputClass}
            value={text}
            maxLength={4000}
            placeholder="hello agents"
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <Button type="submit" variant="primary" busy={busy} disabled={!text.trim()}>
          Create echo task
        </Button>
      </form>
      <InlineError error={error} />
      {echoTasks.length === 0 ? (
        <EmptyState title="No echo tasks in this project" />
      ) : (
        <ul aria-label="Echo tasks" className="divide-y divide-line">
          {echoTasks.map((t) => (
            <li key={t.task_id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
              <TaskStateChip state={t.state} />
              <span className="min-w-0 flex-1 truncate">{t.objective}</span>
              <Mono title={t.task_id}>{shortId(t.task_id)}</Mono>
              <span className="text-xs text-muted">{formatTime(t.updated_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
