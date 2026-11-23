/** Shapes of the review API (`/api/review/...`, Member 10's plug-in). */

export type Verdict = "PASS" | "PARTIAL" | "FAIL";
export type Recommendation = "PASS" | "REVISE" | "ESCALATE";

export interface RevisionPlan {
  task_id: string;
  action: "revise" | "rerun" | "replan" | "escalate";
  required_changes: string[];
}

export interface CreatedTask {
  task_id: string;
  capability: string;
  title: string | null;
  state: string;
  action: string | null;
  parent_task_id: string | null;
}

export interface Decision {
  accepted?: boolean;
  notes?: string;
  overrides?: Record<string, { item_id: string; verdict: Verdict; note: string }>;
  request_changes?: string;
  history?: { by: string; at: string; [k: string]: unknown }[];
}

export interface Round {
  task_id: string;
  state: string;
  created_at: string | null;
  round: number;
  recommendation: Recommendation | null;
  completeness: number | null;
  failures: number;
  stop_reason: string | null;
  plan: { actions?: RevisionPlan[]; rerun?: string[]; waiting?: string[]; stop_reason?: string | null };
  created_tasks: CreatedTask[];
  stale_of: string | null;
  decision: Decision | null;
}

export interface Rounds {
  project_id: string;
  project_state: string;
  rounds: Round[];
}

export interface ReviewItem {
  id: string;
  kind: "requirement" | "constraint" | "deliverable" | "criterion" | "change";
  text: string;
  priority: string;
  covering: string[];
  max_marks: number | null;
  evidence: {
    tests: { name: string; status: string; module: string | null; detail: string }[];
    verification: { claim: string; verdict: string }[];
    deliverables: { name: string; present: boolean | null; where: string }[];
    doc_ungrounded: string[];
    doc_status: string | null;
    violations: string[];
    facts: string[];
    producer_note: string;
    stub: boolean;
  };
}

export interface Decided {
  item: ReviewItem;
  check: { verdict: string; reasons: string[]; category: string | null; no_action: boolean };
  verdict: Verdict;
  source: "objective" | "judge" | "both" | "none" | "human";
  rationale: string;
  votes: { order: string; verdict: Verdict; valid_citations: boolean }[];
  order_sensitive: boolean;
  level: string | null;
  score: number | null;
}

export interface ReviewReport {
  project_id: string;
  requirement_results: { req_id: string; verdict: Verdict; rationale: string; evidence: string[] }[];
  rubric_scores: { criterion_id: string; score: number; max_marks: number }[];
  failures: {
    category: string;
    requirement_id: string | null;
    responsible_task_id: string | null;
    description: string;
  }[];
  revision_requests: RevisionPlan[];
  overall: number;
  recommendation: Recommendation;
}

export interface TaskRow {
  task_id: string;
  capability: string;
  title: string;
  plan_task_id: string | null;
}

export interface ReportDetail {
  report: ReviewReport;
  items: Decided[];
  mode: string | null;
  notes: string[];
  tasks: TaskRow[];
  trace: { round?: number; judge_calls?: number; stop_reason?: string | null; order_sensitive?: string[] };
  decision: Decision | null;
  project_state: string;
}
