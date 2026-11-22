/** Shapes of the documentation API (`/api/docgen/...`, Member 9's plug-in). Mirrors `hmap.agents.docgen.model`. */

export type DocName =
  "readme" | "api" | "architecture" | "summaries" | "report";
export type Verdict = "grounded" | "ungrounded" | "unverified" | "unchecked";

export interface BundleSummary {
  task_id: string;
  capability: string;
  status: "running" | "done";
  mode: "software" | "document" | "none";
  step: string;
  documents: DocName[];
  grounded_pct: number | null;
  checked: number;
  ungrounded: number;
  removed: number;
  unverified: number;
  coverage_pct: number | null;
  examples_run: number;
  examples_failed: number;
  degraded: boolean;
  rounds: number;
  model_calls: number;
  seconds: number | null;
  source: string;
  updated_at: string;
}

export interface Claim {
  kind: string;
  text: string;
  verdict: Verdict;
  why: string;
  doc: string;
  sentence: string;
  line: number;
  by: "rule" | "model";
  evidence: string;
}

export interface ExampleResult {
  doc: string;
  line: number;
  language: string;
  code: string;
  action: "run" | "check" | "skip";
  ok: boolean | null;
  why: string;
  output: string;
  backend: string;
}

export interface Accuracy {
  grounded_pct: number;
  checked: number;
  grounded: number;
  ungrounded: number;
  unverified: number;
  claims: Claim[];
  removed: Claim[];
  examples: ExampleResult[];
  coverage_pct: number | null;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: "component" | "library" | "service";
  modules?: number;
  lines?: number;
  entry?: boolean;
}

export interface GraphEdge {
  from: string;
  to: string;
  count: number;
  kind?: string;
}

export interface DocgenTrace {
  task_id: string;
  mode: string;
  step: string;
  source: string;
  files: number;
  rounds: number;
  stop_reason: string | null;
  scores: number[];
  model_calls: number;
  degraded: boolean;
  citations_removed: string[];
  injected_lines: string[];
  coverage: {
    req_id: string;
    status: string;
    evidence?: string[];
    claims?: string[];
    section?: string;
  }[];
  changed_sections: string[];
  previous_bundle: string | null;
  notes: string[];
  changelog?: string[];
  docstring_patch?: boolean;
}

export interface BundleDetail {
  summary: BundleSummary;
  trace: DocgenTrace;
  accuracy: Accuracy | null;
  documents: Partial<Record<DocName, string>>;
  graph: { nodes: GraphNode[]; edges: GraphEdge[] } | null;
}

export interface CheckResult {
  facts_of: string;
  accuracy: Accuracy;
}
