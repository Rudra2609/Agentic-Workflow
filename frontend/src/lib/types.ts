/**
 * Wire types for the hmap API. They mirror the backend models; keep them in sync with
 *  - backend/src/hmap/core/contracts/states.py      (state enums)
 *  - backend/src/hmap/manager/records.py             (projects, tasks, executions, approvals)
 *  - backend/src/hmap/services/registry/base.py      (agents)
 *  - backend/src/hmap/core/contracts/events.py       (domain events)
 */

export const TASK_STATES = [
  "CREATED",
  "READY",
  "ASSIGNED",
  "ACCEPTED",
  "RUNNING",
  "RESULT_SUBMITTED",
  "REVIEWING",
  "COMPLETED",
  "BLOCKED",
  "CANCELLED",
  "RETRY_SCHEDULED",
  "DEAD_LETTERED",
  "FAILED",
  "NEEDS_REVISION",
] as const;
export type TaskState = (typeof TASK_STATES)[number];

export const TERMINAL_TASK_STATES: ReadonlySet<string> = new Set<TaskState>([
  "COMPLETED",
  "CANCELLED",
  "FAILED",
  "DEAD_LETTERED",
]);

export const EXECUTION_STATUSES = [
  "PENDING",
  "ACTIVE",
  "SUCCEEDED",
  "FAILED",
  "TIMED_OUT",
  "SUPERSEDED",
  "CANCELLED",
  "DEAD_LETTERED",
] as const;
export type ExecutionStatus = (typeof EXECUTION_STATUSES)[number];

export const AGENT_STATES = [
  "STARTING",
  "REGISTERING",
  "AVAILABLE",
  "BUSY",
  "DRAINING",
  "OFFLINE",
  "RECOVERING",
  "FAILED",
] as const;
export type AgentState = (typeof AGENT_STATES)[number];

export const PROJECT_STATES = [
  "CREATED",
  "INGESTING",
  "PLANNING",
  "AWAITING_APPROVAL",
  "EXECUTING",
  "REVIEWING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;
export type ProjectState = (typeof PROJECT_STATES)[number];

export interface ArtifactRef {
  artifact_id: string;
  artifact_type: string;
  version: number;
  uri: string;
  sha256: string;
  media_type: string;
  size_bytes: number;
  created_by: string;
  created_at: string;
  access_scope: string;
  supersedes?: number | null;
}

export interface ContextRef {
  context_id: string;
  version: number;
}

export interface Approval {
  approval_id: string;
  project_id: string;
  graph_version: number | null;
  status: "pending" | "approved" | "rejected";
  comment: string | null;
  requested_at: string;
  decided_at: string | null;
}

/** One pass of the pipeline over a project; earlier runs stay as history. */
export interface Run {
  number: number;
  started_at: string;
  finished_at: string | null;
  outcome: ProjectState | null;
  goal: string | null;
  documents: string[];
  /** Added by the API: tasks of this run. */
  task_count?: number;
  task_states?: Record<string, number>;
}

export interface Project {
  project_id: string;
  name: string;
  owner_id?: string | null;
  description?: string | null;
  runs?: Run[];
  archived?: boolean;
  /** Most recent change of the project or any of its tasks (list and detail views). */
  last_activity_at?: string;
  /** Task counts by state for the newest run (list view). */
  current_run_task_states?: Record<string, number>;
  state: ProjectState;
  state_version: number;
  created_at: string;
  updated_at: string;
  graph_version: number | null;
  plan_task_map: Record<string, string>;
  /** Plan is shown, then approved automatically (no human gate); the human keeps the Stop button. */
  auto_approve: boolean;
  /** False keeps the project on this computer: no step uses a cloud model, even with team keys set. */
  cloud_ok: boolean;
  /** Sprint 4: each result (requirements, plan) is checked and improved before it is used (slower). */
  refine?: boolean;
  /** Set when a human pressed Stop (project state CANCELLED). */
  stopped_reason: string | null;
  /** Only present on `GET /projects/{id}` (and the create/approval responses). */
  approvals?: Approval[];
}

export interface Task {
  task_id: string;
  project_id: string;
  capability: string;
  objective: string;
  title: string | null;
  acceptance_criteria: string[];
  inputs: Record<string, unknown>;
  artifact_refs: ArtifactRef[];
  context_refs: ContextRef[];
  depends_on: string[];
  parent_task_id: string | null;
  plan_task_id: string | null;
  /** A plan step dropped by a replan (Sprint 3): kept as history, not part of the current plan. */
  replaced?: boolean;
  /** Run number this task belongs to. */
  run?: number;
  priority: string;
  needs_approval: boolean;
  state: TaskState;
  state_version: number;
  active_execution_id: string | null;
  attempts: number;
  retries: number;
  rejections: number;
  rejected_by: string[];
  retry_at: string | null;
  last_error: Record<string, unknown> | null;
  blocked_by: string[];
  created_at: string;
  updated_at: string;
}

export interface Execution {
  execution_id: string;
  task_id: string;
  attempt: number;
  status: ExecutionStatus;
  agent_id: string | null;
  lease_until: string | null;
  orphaned_at: string | null;
  outcome: string | null;
  result_refs: ArtifactRef[];
  result_summary: string | null;
  error: Record<string, unknown> | null;
  superseded_by: string | null;
  evidence: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
}

export interface TaskDetail extends Task {
  executions: Execution[];
}

export interface Agent {
  agent_id: string;
  plugin: string | null;
  capabilities: string[];
  protocol_version: string;
  state: AgentState;
  max_slots: number;
  available_slots: number;
  current_execution_ids: string[];
  lease_until: string;
  last_heartbeat: string;
  is_stub: boolean;
  state_version: number;
}

export interface CapabilityRow {
  capability: string;
  status: "real" | "stub" | "missing";
  plugin: string | null;
  agent: string | null;
  priority: number | null;
}

export interface DeadLetter {
  queue: string;
  reason: string;
  attempts: number;
  history: string[];
  /** Hidden (null) for platform-level messages that belong to no project. */
  body: Record<string, unknown> | null;
  project_id: string | null;
}

export interface User {
  user_id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface Me {
  user: User;
  session_expires_at?: string;
}

/** `GET /projects/{id}/artifacts`: a stored file plus the task that produced it. */
export interface ArtifactItem extends ArtifactRef {
  /** Uploads only: the name it was uploaded as ("Part A/brief.pdf", "request.txt" for a typed request). */
  name?: string | null;
  produced_by: {
    task_id: string;
    task_title: string;
    capability: string;
    run: number;
    agent_id: string | null;
  } | null;
}

export interface Health {
  status: string;
  bus: string;
  queues: Record<string, number>;
}

/** One item of the live feed (`GET /api/events`, WebSocket `/api/ws/events`): a DomainEvent plus the feed `seq`. */
export interface HmapEvent {
  seq: number;
  event_id: string;
  event_type: string;
  aggregate_id: string;
  aggregate_version?: number;
  occurred_at: string;
  schema_version?: string;
  project_id: string | null;
  correlation_id?: string | null;
  traceparent?: string | null;
  data: Record<string, unknown>;
}

export interface UploadedDocument {
  artifact_id: string;
  name: string;
  /** Folder it was uploaded from ("Part A"), or null. */
  folder: string | null;
  /** folder/name, as listed in the run's documents. */
  path: string;
}

export interface UploadResult {
  /** The first document (kept for single-file callers). */
  artifact: ArtifactRef;
  artifacts?: ArtifactRef[];
  documents?: UploadedDocument[];
  filename: string | null;
  run?: number;
}

export interface NewTask {
  capability: string;
  objective: string;
  acceptance_criteria?: string[];
  inputs?: Record<string, unknown>;
  depends_on?: string[];
}

export interface CancelResult {
  cancelled: boolean;
  task: TaskDetail;
}

/** `POST /projects/{id}/stop` (the Stop button). */
export interface StopResult {
  cancelled_tasks: number;
  project: Project;
}
