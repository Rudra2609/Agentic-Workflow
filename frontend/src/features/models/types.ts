/** Shapes of the models API (`/api/models/...`, Member 11's plug-in, Sprint 11). */

export interface ModelSpec {
  id: string;
  family: string;
  params_b: number | null;
  quant: string | null;
  ctx: number | null;
  backend: "ollama" | "llamacpp" | "mlx" | "cloud";
  mem_gb: number | null;
  tok_s: number | null;
  roles_ok: string[];
  status: "installed" | "available" | "missing" | "disabled";
}

export interface ModelRow {
  spec: ModelSpec;
  digest: string | null;
  source: string;
  pinned: boolean;
  resident_gb: number | null;
  last_seen: string;
}

export interface Registry {
  models: ModelRow[];
  ollama_up: boolean | null;
  error: string;
}

export interface Hardware {
  hardware: {
    platform: string;
    chip: string;
    total_gb: number;
    free_gb: number;
    swap_used_gb: number;
    gpu: string;
    docker_vm_gb: number | null;
    resident: Record<string, number>;
    ollama: boolean;
    notes: string[];
  };
  feasibility: { model: string; fit: "fits" | "fits_alone" | "does_not_fit" | "unknown"; need_gb: number | null; why: string }[];
  sizing: { ram_gb: number; model_budget_gb: number; fits: string[] }[];
}

export interface RouteRecord {
  id: string;
  at: string;
  decision: { role: string; model: string; backend: string; reason: string };
  plugin: string;
  est_tokens: number;
  chain: string[];
  rule: string;
  answered_by: string | null;
  ok: boolean | null;
  latency_s: number | null;
  attempts: number;
  rate_limited: number;
  error: string;
}

export interface Routes {
  enabled: boolean;
  now: string;
  summary: { decisions: number; answered_by: Record<string, number>; failed: number; rules: Record<string, number>; rate_limited: number; attempts: number };
  routes: RouteRecord[];
}

export interface QuickSuite {
  items: number;
  answered: number;
  score: number | null;
  valid_json?: number | null;
}

export interface QuickResult {
  model: string;
  mode: string;
  quality: number | null;
  coverage: number;
  suites: Record<string, QuickSuite>;
}

export interface Bench {
  files: Record<string, unknown>;
  table: Record<string, Record<string, number>>;
  table_path: string;
}

export interface FineTune {
  runs: Record<string, unknown>[];
  files: Record<string, unknown>;
}
