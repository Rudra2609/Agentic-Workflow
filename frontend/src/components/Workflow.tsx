"use client";

/**
 * Workflow visuals: the pipeline stage rail and the plan's dependency graph. Every node reflects a reported state;
 * motion (the pulse) only appears for steps the backend reports as running.
 */
import { roleOf, taskStateText } from "@/lib/plain";
import type { Task } from "@/lib/types";
import { layoutGraph, NODE_H, NODE_W, type Stage, type StageStatus } from "@/lib/workflow";

import { cx } from "./ui";

// Stage markers are keycaps: lit (pressed-in colour) when done, raised and glowing while active.
const STAGE_LOOK: Record<StageStatus, { cap: string; label: string; icon: string }> = {
  done: { cap: "bg-success text-white dark:text-canvas [--hm-key-edge:color-mix(in_oklab,var(--hm-success)_60%,black)]", label: "Done", icon: "✓" },
  active: { cap: "hm-key-accent bg-accent text-on-accent", label: "In progress", icon: "●" },
  waiting: { cap: "bg-warning text-white dark:text-canvas [--hm-key-edge:color-mix(in_oklab,var(--hm-warning)_60%,black)]", label: "Waiting for you", icon: "!" },
  pending: { cap: "bg-surface text-muted border border-line-strong", label: "Not started", icon: "" },
  failed: { cap: "hm-key-danger bg-danger text-white dark:text-canvas", label: "Problem", icon: "×" },
  stopped: { cap: "bg-surface-2 text-muted border border-line-strong", label: "Stopped", icon: "–" },
  skipped: { cap: "bg-surface-2 text-fg-2 border border-line-strong", label: "Automatic", icon: "↷" },
};

export function StageRail({
  stages,
  selectedTaskId,
  onSelectTask,
}: {
  stages: readonly Stage[];
  selectedTaskId: string | null;
  onSelectTask: (id: string) => void;
}) {
  return (
    <ol aria-label="Workflow stages" className="grid gap-y-3 sm:grid-cols-5">
      {stages.map((s, i) => {
        const look = STAGE_LOOK[s.status];
        const clickable = Boolean(s.taskId);
        const body = (
          <>
            <span className="flex items-center">
              <span
                aria-hidden="true"
                className={cx(
                  "hm-key grid size-9 shrink-0 place-items-center rounded-[5px] text-sm font-bold",
                  look.cap,
                  s.status === "active" && "animate-pulse",
                )}
              >
                {look.icon}
              </span>
              {i < stages.length - 1 && (
                <span aria-hidden="true" className={cx("mx-3 hidden h-[3px] flex-1 rounded-full sm:block", s.status === "done" || s.status === "skipped" ? "bg-success/60" : "bg-line")} />
              )}
            </span>
            <span className="mt-2 block pr-3">
              <span className="font-display block text-[15px] font-semibold text-fg">{s.title}</span>
              <span className="block text-2xs font-medium text-muted">{look.label}</span>
              <span className="mt-0.5 block text-xs text-fg-2">{s.detail}</span>
            </span>
          </>
        );
        return (
          <li key={s.id} aria-current={s.status === "active" || s.status === "waiting" ? "step" : undefined}>
            {clickable ? (
              <button
                type="button"
                onClick={() => onSelectTask(s.taskId!)}
                aria-pressed={selectedTaskId === s.taskId}
                className={cx("block w-full rounded-md p-1 text-left hover:bg-hover", selectedTaskId === s.taskId && "bg-selected")}
              >
                {body}
              </button>
            ) : (
              <div className="p-1">{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

const NODE_TONE: Record<string, string> = {
  neutral: "border-line-strong",
  progress: "border-accent",
  success: "border-success/60",
  warning: "border-warning",
  danger: "border-danger",
  muted: "border-line border-dashed",
};

function NodeCard({ task, selected, stub, onSelect }: { task: Task; selected: boolean; stub: boolean; onSelect: () => void }) {
  const st = taskStateText(task.state);
  const role = roleOf(task.capability);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`${task.title || task.objective}: ${st.label}, ${role.name}`}
      className={cx(
        "hm-slip flex h-full w-full flex-col justify-center rounded-[3px] border-l-4 px-3 text-left",
        NODE_TONE[st.tone],
        selected && "ring-2 ring-focus ring-offset-2 ring-offset-canvas",
        task.state === "COMPLETED" && "opacity-80",
      )}
    >
      <span className="truncate text-xs font-medium text-fg">{task.title || task.objective}</span>
      <span className="mt-0.5 flex items-center gap-1.5 text-2xs text-muted">
        <span className={cx(st.tone === "danger" && "text-danger", st.tone === "progress" && "text-accent-ink", st.tone === "warning" && "text-warning", st.tone === "success" && "text-success")}>
          {st.label}
        </span>
        <span aria-hidden="true">·</span>
        <span className="truncate">{role.name}{stub ? " (placeholder)" : ""}</span>
      </span>
    </button>
  );
}

export function PlanGraph({
  tasks,
  selectedTaskId,
  onSelectTask,
  stubCapabilities,
}: {
  tasks: readonly Task[];
  selectedTaskId: string | null;
  onSelectTask: (id: string) => void;
  stubCapabilities: ReadonlySet<string>;
}) {
  const byId = new Map(tasks.map((t) => [t.task_id, t]));
  const layout = layoutGraph(tasks.map((t) => ({ id: t.task_id, dependsOn: t.depends_on })));
  const ordered = [...layout.nodes].sort((a, b) => a.layer - b.layer || a.row - b.row);
  return (
    <>
      {/* canvas (tablet and up) */}
      <div className="hidden overflow-x-auto pb-2 sm:block">
        <div className="relative" style={{ width: layout.width, height: layout.height }}>
          <svg aria-hidden="true" width={layout.width} height={layout.height} className="absolute inset-0 overflow-visible">
            {layout.edges.map((e) => {
              const from = byId.get(e.from);
              const done = from?.state === "COMPLETED";
              return (
                <path
                  key={`${e.from}-${e.to}`}
                  d={e.path}
                  fill="none"
                  strokeWidth={1.5}
                  className={done ? "stroke-success/50" : "stroke-line-strong"}
                  strokeDasharray={done ? undefined : "4 3"}
                />
              );
            })}
          </svg>
          <ol aria-label="Plan steps">
            {ordered.map((n) => {
              const t = byId.get(n.id)!;
              return (
                <li key={n.id} className="absolute" style={{ left: n.x, top: n.y, width: NODE_W, height: NODE_H }}>
                  <NodeCard task={t} selected={selectedTaskId === n.id} stub={stubCapabilities.has(t.capability)} onSelect={() => onSelectTask(n.id)} />
                </li>
              );
            })}
          </ol>
        </div>
        <p className="mt-2 text-2xs text-muted">Solid lines: the earlier step is done. Dashed: still waiting on it.</p>
      </div>
      {/* list (phones) */}
      <ol aria-label="Plan steps" className="space-y-2 sm:hidden">
        {ordered.map((n) => {
          const t = byId.get(n.id)!;
          return (
            <li key={n.id} className="h-16">
              <NodeCard task={t} selected={selectedTaskId === n.id} stub={stubCapabilities.has(t.capability)} onSelect={() => onSelectTask(n.id)} />
            </li>
          );
        })}
      </ol>
    </>
  );
}
