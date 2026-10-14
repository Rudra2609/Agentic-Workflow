/** Shapes returned by `/api/research/...` (Member 5's plug-in). Mirrors `ResearchReport` (contract) and the
 * `research-trace` artifact. */

export type SubStatus = "open" | "covered" | "partial" | "exhausted";

export interface SubQuestion {
  id: string;
  question: number;
  text: string;
  queries: string[];
  success_criteria: string;
  coverage: number;
  status: SubStatus;
}

export interface Claim {
  id: string;
  text: string;
  evidence_ids: string[];
}

export interface ArtifactRefLite {
  artifact_id: string;
  artifact_type: string;
  version: number;
}

export interface Evidence {
  id: string;
  url: string;
  quote: string;
  content_sha256: string;
  retrieved_at: string;
  sub_question: string | null;
  page_artifact: ArtifactRefLite | null;
}

export interface Source {
  url: string;
  title: string;
  score: number | null;
  score_breakdown: Record<string, number>;
  provider: string | null;
  kind: "web" | "wiki" | "arxiv" | "local" | null;
  retrieved_at: string | null;
  content_sha256: string | null;
  page_artifact: ArtifactRefLite | null;
}

export interface Report {
  task_id: string;
  questions: string[];
  claims: Claim[];
  evidence: Evidence[];
  sources: Source[];
  coverage: Record<string, number>;
  stop_reason: string;
  summary_markdown: string | null;
  sub_questions: SubQuestion[];
}

export interface Round {
  index: number;
  queries: { sub_question: string; provider: string; query: string; hits: number }[];
  hits: number;
  fetched: number;
  fetch_failures: Record<string, number>;
  selected: { sub_question: string; url: string; chunk: string; score: number; breakdown: Record<string, number> }[];
  triaged: number;
  relevant: number;
  quotes_proposed: number;
  quotes_dropped: number;
  new_evidence: number;
  novelty: number;
  coverage: Record<string, number>;
  tokens: number;
  seconds: number;
}

export interface Trace {
  task_id: string;
  mode: string;
  providers: string[];
  status: "running" | "stopped";
  rounds: Round[];
  stop_reason: string | null;
  planner: string;
  synthesis: string;
  claims_dropped: string[];
  tokens: number;
  model_calls: number;
  seconds: number;
  notes: string[];
}

export interface RunSummary {
  task_id: string;
  status: "running" | "stopped" | null;
  mode: string | null;
  providers: string[] | null;
  rounds: number;
  stop_reason: string | null;
  tokens: number | null;
  model_calls: number | null;
  seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
  questions: string[];
  claims: number;
  evidence: number;
  sources: number;
  sub_questions: number;
  covered: number;
  coverage: number;
}

export interface RunDetail {
  summary: RunSummary;
  trace: Trace;
  report: Report | null;
  brief: { questions: string[]; scope: string } | null;
}

export interface PageView {
  url: string;
  title: string;
  kind: string;
  provider: string;
  retrieved_at: string;
  content_sha256: string;
  text: string;
  spans: { evidence_id: string; start: number; end: number }[];
  injection_lines_removed: number;
  license: string | null;
}

export interface Providers {
  mode: "online" | "cached" | "local";
  providers: string[];
  corpus: { pages: number; by_kind: Record<string, number> };
}
