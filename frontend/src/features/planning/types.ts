/** Shapes of the planning API (`/api/planning`, Member 3) and of the shared `TaskGraph` contract. */

export type PlanPhase = "research" | "design" | "implement" | "test" | "document" | "review";
export type PlanPriority = "low" | "normal" | "high" | "urgent";

export interface PlanTask {
  id: string;
  title: string;
  description: string;
  agent_capability: string;
  requirement_ids: string[];
  acceptance_criteria: string[];
  depends_on: string[];
  priority: PlanPriority;
  est_effort: number | null;
  phase: PlanPhase;
  research_questions: string[];
}

export interface PlanGroup {
  id: string;
  name: string;
  task_ids: string[];
  parent_id: string | null;
}

export interface Milestone {
  name: string;
  task_ids: string[];
}

export interface TaskGraph {
  project_id: string;
  version: number;
  tasks: PlanTask[];
  roadmap: { phases: PlanGroup[]; milestones: Milestone[]; markdown: string | null };
  coverage_matrix: Record<string, string[]>;
  edges?: { from: string; to: string }[];
}

export interface Issue {
  code: string;
  severity: "error" | "warning";
  message: string;
  task_id: string | null;
  requirement_id: string | null;
}

export interface Schedule {
  layers: string[][];
  critical_path: string[];
  earliest_start: Record<string, number>;
  slack: Record<string, number>;
  total_effort: number;
  makespan: number;
}

export interface PlanReport {
  graph_version: number;
  origin: "generated" | "edited" | "replanned";
  method: "llm" | "rules" | "mixed";
  project_kind: string;
  prompt_version: string;
  answered_by: Record<string, number>;
  llm_calls: number;
  fallbacks: string[];
  repairs: string[];
  issues: Issue[];
  flagged: Record<string, string>;
  deliverables: Record<string, string[]>;
  questions: string[];
  low_confidence: string[];
  edges: Record<string, number>;
  schedule: Schedule;
  feedback: string | null;
  author: string | null;
}

export interface PlanVersion {
  version: number;
  created_by: string;
  created_at: string;
}

export interface PlanResponse {
  artifact: { artifact_id: string; version: number; created_by: string; created_at: string };
  graph: TaskGraph;
  report: PlanReport | null;
  versions: PlanVersion[];
  /** The version the Manager is running (or waiting to approve). */
  submitted_version: number | null;
  project_state: string;
  /** Plan step id -> task state, for the current run. */
  states: Record<string, string>;
  requirements: { artifact_id: string | null; used_version: number | null; latest_version: number | null; changed: boolean };
}

export interface Capabilities {
  capabilities: string[];
  by_phase: Record<PlanPhase, string[]>;
}
