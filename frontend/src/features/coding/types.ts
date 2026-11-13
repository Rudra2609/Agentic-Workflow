/** Shapes returned by the coding API (`/api/coding`, Member 7's plug-in). */

export type Outcome = "success" | "partial" | "failure" | "";
export type CheckStatus = "passed" | "failed" | "skipped";

export interface RunSummary {
  task_id: string;
  capability: string;
  status: "running" | "done";
  outcome: Outcome;
  stop_reason: string;
  objective: string;
  base: string;
  template: string | null;
  files_changed: string[];
  checks: Record<string, CheckStatus>;
  model_calls: number;
  tokens: number;
  edits: number;
  edits_rejected: number;
  commands: number;
  denials: number;
  flags: string[];
  revision_round: number;
  original_task_id: string | null;
  head_version: number | null;
  updated_at: string;
}

export interface Step {
  n: number;
  kind: string;
  summary: string;
  prompt_tokens: number;
  completion_tokens: number;
  ok: boolean;
}

export interface EditRecord {
  step: number;
  files: string[];
  ok: boolean;
  error: string | null;
  notes: string[];
}

export interface CommandRecord {
  step: number;
  cmd: string;
  exit_code: number | null;
  timed_out: boolean;
  duration_s: number;
  output: string;
  denied: string | null;
}

export interface Check {
  name: string;
  status: CheckStatus;
  detail: string;
}

export interface CodingTrace {
  task_id: string;
  status: "running" | "done";
  objective: string;
  acceptance_criteria: string[];
  base: string;
  template: string | null;
  required_changes: string[];
  located: { path: string; score: number }[];
  plan: { summary?: string; files_to_modify?: string[]; files_to_create?: string[]; steps?: string[] } | null;
  steps: Step[];
  edits: EditRecord[];
  commands: CommandRecord[];
  denials: string[];
  flags: string[];
  checks: Check[];
  reflections: string[];
  files_changed: string[];
  stop_reason: string;
  outcome: Outcome;
  notes: string[];
}

export interface RunDetail {
  summary: RunSummary;
  trace: CodingTrace;
  changeset: { task_id: string; files_changed: string[]; notes: string } | null;
  diff: string;
  revisions: { task_id: string; state: string; objective: string }[];
}
