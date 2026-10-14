/** Shapes of the operations API (`/api/ops`, Member 4). */

export interface Overview {
  tasks_by_state: Record<string, number>;
  dead_lettered: number;
  agents_by_state: Record<string, number>;
  queues: Record<string, number>;
  tracing: boolean;
  links: { jaeger: string; grafana: string; prometheus: string };
  metrics_path: string;
}

export interface TaskRow {
  task_id: string;
  project_id: string;
  project_name: string | null;
  capability: string;
  title: string;
  state: string;
  attempts: number;
  replays: number;
  last_error: { code?: string; message?: string; attempt?: number; agent_id?: string | null } | null;
  updated_at: string;
  plan_task_id: string | null;
}

export interface BusDeadLetter {
  queue: string;
  reason: string;
  attempts: number;
  message_type: string | null;
  task_id: string | null;
  project_id: string;
  message_id: string | null;
}

export interface Action {
  action: "replay" | "replan" | "run_again";
  allowed: boolean;
  label: string;
  why: string;
}

export interface Explanation {
  task: {
    task_id: string;
    project_id: string;
    capability: string;
    title: string | null;
    objective: string;
    state: string;
    attempts: number;
    retries: number;
    replays: number;
    run: number;
    plan_task_id: string | null;
    depends_on: string[];
    blocked_by: string[];
    last_error: Record<string, unknown> | null;
    created_at: string;
    updated_at: string;
  };
  verdict: { status: string; headline: string; facts: string[]; actions: Action[]; cause: string | null };
  executions: {
    execution_id: string;
    attempt: number;
    status: string;
    agent_id: string | null;
    created_at: string;
    updated_at: string;
    error: { code?: string; message?: string } | null;
    superseded_by: string | null;
    orphaned_at: string | null;
    outcome: string | null;
    late_reports: { message_type: string; note: string; received_at: string; sender: string }[];
  }[];
  messages: { message_id: string; queue: string; execution_id: string | null; created_at: string; published_at: string | null; processed_by: string[] }[];
  timeline: { seq: number | null; at: string | null; event_type: string; summary: string }[];
  dependencies: { task_id: string; title: string | null; state: string }[];
  dependants: { task_id: string; title: string | null; state: string }[];
  trace: { trace_ids: string[]; tracing: boolean; links: string[] };
  artifacts: { artifact_id: string; artifact_type: string; version: number; size_bytes: number | null }[];
}
