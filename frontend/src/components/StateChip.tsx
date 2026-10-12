/** Colour-coded state chips for tasks, projects, executions and agents. */
import { humanize } from "@/lib/format";
import type { AgentState, ExecutionStatus, ProjectState, TaskState } from "@/lib/types";

import { cx } from "./ui";

export type Tone = "neutral" | "info" | "progress" | "success" | "warning" | "danger" | "muted";

export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg-2",
  info: "bg-info-soft text-info",
  progress: "bg-accent-soft text-accent-ink",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  muted: "bg-surface-2 text-muted",
};

const DOT_CLASSES: Record<Tone, string> = {
  neutral: "bg-fg-2",
  info: "bg-info",
  progress: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  muted: "bg-disabled",
};

export const TASK_STATE_TONES: Record<TaskState, Tone> = {
  CREATED: "neutral",
  READY: "info",
  ASSIGNED: "info",
  ACCEPTED: "progress",
  RUNNING: "progress",
  RESULT_SUBMITTED: "progress",
  REVIEWING: "progress",
  COMPLETED: "success",
  BLOCKED: "warning",
  CANCELLED: "muted",
  RETRY_SCHEDULED: "warning",
  DEAD_LETTERED: "danger",
  FAILED: "danger",
  NEEDS_REVISION: "warning",
};

export const PROJECT_STATE_TONES: Record<ProjectState, Tone> = {
  CREATED: "neutral",
  INGESTING: "progress",
  PLANNING: "progress",
  AWAITING_APPROVAL: "warning",
  EXECUTING: "progress",
  REVIEWING: "progress",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "muted",
};

export const EXECUTION_STATUS_TONES: Record<ExecutionStatus, Tone> = {
  PENDING: "info",
  ACTIVE: "progress",
  SUCCEEDED: "success",
  FAILED: "danger",
  TIMED_OUT: "warning",
  SUPERSEDED: "muted",
  CANCELLED: "muted",
  DEAD_LETTERED: "danger",
};

export const AGENT_STATE_TONES: Record<AgentState, Tone> = {
  STARTING: "info",
  REGISTERING: "info",
  AVAILABLE: "success",
  BUSY: "progress",
  DRAINING: "warning",
  OFFLINE: "muted",
  RECOVERING: "warning",
  FAILED: "danger",
};

const ACTIVE_STATES = new Set(["RUNNING", "ACTIVE", "BUSY", "INGESTING", "PLANNING", "EXECUTING", "REVIEWING"]);

function toneOf<S extends string>(map: Record<S, Tone>, state: string): Tone {
  return (map as Record<string, Tone>)[state] ?? "neutral";
}

export function StateChip({ state, tone, kind }: { state: string; tone: Tone; kind: string }) {
  return (
    <span
      data-state={state}
      data-tone={tone}
      title={`${kind} state: ${state}`}
      className={cx(
        "inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-2xs font-medium whitespace-nowrap",
        TONE_CLASSES[tone],
      )}
    >
      <span
        aria-hidden="true"
        className={cx("size-1.5 rounded-full", DOT_CLASSES[tone], ACTIVE_STATES.has(state) && "animate-pulse")}
      />
      {humanize(state)}
    </span>
  );
}

export function TaskStateChip({ state }: { state: TaskState | string }) {
  return <StateChip kind="Task" state={state} tone={toneOf(TASK_STATE_TONES, state)} />;
}

export function ProjectStateBadge({ state }: { state: ProjectState | string }) {
  return <StateChip kind="Project" state={state} tone={toneOf(PROJECT_STATE_TONES, state)} />;
}

export function ExecutionStatusChip({ status }: { status: ExecutionStatus | string }) {
  return <StateChip kind="Execution" state={status} tone={toneOf(EXECUTION_STATUS_TONES, status)} />;
}

export function AgentStateChip({ state }: { state: AgentState | string }) {
  return <StateChip kind="Agent" state={state} tone={toneOf(AGENT_STATE_TONES, state)} />;
}
