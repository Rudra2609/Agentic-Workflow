/** Shapes returned by the verify API (`/api/verify/...`, Member 6's plug-in). */

export type Verdict = "VERIFIED" | "UNSUPPORTED" | "CONFLICTING" | "NEEDS_MORE_RESEARCH";
export type Label = "supports" | "refutes" | "not_enough";

export interface ArtifactRefLite {
  artifact_id: string;
  artifact_type: string;
  version: number;
}

export interface RunSummary {
  task_id: string;
  status: "running" | "done";
  round: number;
  research_task_id: string | null;
  layers: string[];
  claims: number;
  verified: number;
  unsupported: number;
  conflicting: number;
  needs_more: number;
  model_calls: number;
  tokens: number;
  seconds: number;
  started_at: string | null;
  finished_at: string | null;
  follow_up_questions: string[];
  follow_up_of: ArtifactRefLite | null;
  notes: string[];
}

export interface L1Result {
  evidence_id: string;
  ok: boolean;
  reason: string;
  detail: string;
}

export interface Judgement {
  label: Label;
  rationale: string;
  by: "model" | "rules";
  swapped_label: Label | null;
  guard: string;
}

export interface Passage {
  url: string;
  host: string;
  title: string;
  text: string;
  overlap: number;
  origin: "independent" | "counter";
  query: string;
  published: string | null;
}

export interface Comparison {
  passage: Passage;
  signals: string[];
  judgement: Judgement | null;
}

export interface AtomCheck {
  atom_id: string;
  text: string;
  check_worthy: boolean;
  l1: L1Result[];
  l2: Judgement | null;
  l3_queries: string[];
  l3_passages: number;
  l4: Comparison[];
  independent_hosts: string[];
  row: string;
  verdict: Verdict;
  confidence: number;
  explanation: string;
}

export interface EvidenceView {
  id: string;
  url: string;
  quote: string;
  content_sha256: string;
  title?: string;
  page_artifact: ArtifactRefLite | null;
}

export interface ClaimCheck {
  claim_id: string;
  text: string;
  evidence_ids: string[];
  atoms: AtomCheck[];
  verdict: Verdict;
  confidence: number;
  explanation: string;
  supporting: string[];
  contradicting: string[];
  evidence?: EvidenceView[];
}

export interface Trace {
  task_id: string;
  research_task_id: string | null;
  layers: string[];
  round: number;
  status: "running" | "done";
  claims: ClaimCheck[];
  follow_up_questions: string[];
  model_calls: number;
  tokens: number;
  seconds: number;
  notes: string[];
}

export interface FollowUpTask {
  task_id: string;
  capability: string;
  state: string;
  objective: string;
}

export interface RunDetail {
  summary: RunSummary;
  trace: Trace;
  research_questions: string[];
  follow_ups: FollowUpTask[];
}

export interface PageView {
  url: string;
  title: string;
  text: string;
  content_sha256: string;
  spans: { evidence_id: string; start: number; end: number }[];
  license: string | null;
}
