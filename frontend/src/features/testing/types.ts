/** Shapes of the testing API (`/api/testing/...`, Member 8's plug-in). Mirrors `hmap.agents.testing.model`. */

export type StageStatus = "passed" | "failed" | "skipped" | "error";
export type Category =
  | "SYNTAX"
  | "IMPORT"
  | "ASSERTION"
  | "TIMEOUT"
  | "CRASH"
  | "SECURITY"
  | "LINT"
  | "ENV";

export interface RunSummary {
  task_id: string;
  status: "running" | "done";
  passed: boolean;
  backend: "docker" | "local" | "none";
  objective: string;
  stages: Record<string, StageStatus>;
  tests: number;
  tests_failed: number;
  failures: number;
  lint: number;
  flaky: number;
  coverage: number | null;
  pass_ratio: number;
  loop_round: number;
  coding_task_id: string | null;
  generated: number;
  seconds: number;
  updated_at: string;
}

export interface StageRecord {
  name: string;
  status: StageStatus;
  duration_s: number;
  detail: string;
  tests: number;
  tests_failed: number;
}

export interface StepRecord {
  stage: string;
  name: string;
  cmd: string;
  exit_code: number | null;
  timed_out: boolean;
  duration_s: number;
  output: string;
}

export interface Failure {
  stage: string;
  category: Category;
  file: string | null;
  line: number | null;
  test: string | null;
  message: string;
  hint: string | null;
  hint_by: "rule" | "model" | "none";
  generated: boolean;
  flaky: boolean;
  fuzz?: boolean;
}

export interface TestingTrace {
  task_id: string;
  status: "running" | "done";
  backend: "docker" | "local" | "none";
  isolation: string;
  workspace_from: string;
  coding_task_id: string | null;
  objective: string;
  acceptance_criteria: string[];
  files: number;
  stages: StageRecord[];
  steps: StepRecord[];
  failures: Failure[];
  flaky: string[];
  generated: {
    file?: string | null;
    kept?: string[];
    dropped?: Record<string, string>;
    note?: string;
  };
  coverage: number | null;
  mutation?: {
    total: number;
    killed: number;
    score: number | null;
    survived: { file: string; line: number; op: string }[];
    error: string | null;
  } | null;
  fuzz?: {
    targets: number;
    functions?: string[];
    findings?: number;
    note?: string;
    error?: string;
  } | null;
  dependencies?: {
    audited: string[];
    unpinned: string[];
    vulnerable: { dependency: string; id: string; summary?: string }[];
    source: string;
    note: string;
  } | null;
  language?: string;
  quarantined?: string[];
  passed: boolean;
  pass_ratio: number;
  loop: { round: number; origin_task_id: string | null; history: number[] };
  model_calls: number;
  notes: string[];
}

export interface RunDetail {
  summary: RunSummary;
  trace: TestingTrace;
  report: { passed: boolean } | null;
  generated_tests: string | null;
  loop: RunSummary[];
}

export interface QuarantineEntry {
  flaky: number;
  clean_passes: number;
  first_seen: string;
  last_seen: string;
  last_task_id: string | null;
}

export interface Quarantine {
  project_id: string;
  tests: Record<string, QuarantineEntry>;
  released: string[];
  release_after: number;
}
