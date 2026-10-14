/** Shapes of the refinement API (`/api/refine`, Member 4). */

export type Severity = "info" | "minor" | "major" | "critical";
export type Category =
  | "FORMAT"
  | "SCHEMA"
  | "OMISSION"
  | "HALLUCINATION"
  | "FACTUAL"
  | "LOGIC"
  | "REQUIREMENT_VIOLATION"
  | "CONSISTENCY"
  | "STYLE"
  | "SAFETY";
export type StopReason = "max_iters" | "threshold" | "no_critical_issues" | "plateau" | "budget" | "tests_pass" | "cancelled" | "error";

export interface Issue {
  category: Category;
  severity: Severity;
  description: string;
  location?: string | null;
  evidence?: string | null;
  fix_hint?: string | null;
}

export interface Critique {
  score: number;
  issues: Issue[];
  critic?: string | null;
}

export interface CriticScore {
  critic: string;
  score: number;
  issues: number;
}

export interface Iteration {
  index: number;
  score: number;
  tokens: number;
  duration_s: number;
  critique: Critique;
  strategy: string | null;
  reflection: string | null;
  revision_notes: string[];
  rejected_changes: string[];
  /** LLM critics skipped this round ("judge: ReplayMissError"): only the code checks scored it. */
  critic_errors?: string[];
  critics: CriticScore[];
  issues_by_category: Record<string, number>;
}

export interface RefineRun {
  run_id: string;
  project_id: string;
  task_id: string | null;
  capability: string | null;
  subject: string;
  status: "running" | "stopped";
  iterations: Iteration[];
  best_iteration: number | null;
  stop_reason: StopReason | null;
  base_score: number | null;
  best_score: number | null;
  tokens: number;
  model_calls: number;
  seconds: number;
  started_at: string;
  updated_at: string;
  error: string | null;
  applied: boolean;
  output_artifact: { artifact_id: string; artifact_type: string; version: number } | null;
  spec: { producer: string; critics: string[]; reviser: string; stop_policy: Record<string, unknown> };
}

export interface RunSummary {
  run_id: string;
  task_id: string | null;
  capability: string | null;
  subject: string;
  status: "running" | "stopped";
  iterations: number;
  best_iteration: number | null;
  stop_reason: StopReason | null;
  base_score: number | null;
  best_score: number | null;
  tokens: number;
  model_calls: number;
  seconds: number;
  started_at: string;
  updated_at: string;
  applied: boolean;
  error: string | null;
  output_artifact: RefineRun["output_artifact"];
  issues_by_category: Record<string, number>;
  scores: number[];
}

export interface DiffChange {
  path: string;
  op: "added" | "removed" | "changed";
  before: unknown;
  after: unknown;
  added_items?: unknown[];
  removed_items?: unknown[];
}

export interface Policy {
  default: Record<string, unknown>;
  hard_max_iters: number;
}
