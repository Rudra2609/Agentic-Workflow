/**
 * Client for the planning API (`/api/planning/...`, mounted by Member 3's plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { Capabilities, Issue, PlanResponse, TaskGraph } from "./types";

const BASE = `${API_URL}/api/planning`;

/** A refused edit: the server's message plus the problems it found (cycle, unknown capability, ...). */
export class PlanRejected extends Error {
  readonly issues: Issue[];

  constructor(message: string, issues: Issue[]) {
    super(message);
    this.issues = issues;
  }
}

async function call<T>(path: string, init: RequestInit & { signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.method && init.method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store",
                                           credentials: API_URL ? "include" : "same-origin" });
  } catch (cause) {
    if (init.signal?.aborted) throw cause;
    throw new ApiError("The HMAP server is not reachable.", { kind: "network", path, cause });
  }
  const text = await res.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    /* keep the text */
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | undefined)?.detail;
    if (res.status === 422 && detail && typeof detail === "object" && "issues" in detail) {
      const d = detail as { message?: string; issues?: Issue[] };
      throw new PlanRejected(d.message ?? "The plan was not saved.", d.issues ?? []);
    }
    throw new ApiError(describeErrorBody(body, `Request failed (${res.status})`), {
      kind: "http", status: res.status, path, detail: body,
    });
  }
  return body as T;
}

const pid = (projectId: string) => encodeURIComponent(projectId);

/** The newest plan of a project (or one version of it), or `null` before a plan exists. */
export async function getPlan(projectId: string, signal?: AbortSignal, version?: number): Promise<PlanResponse | null> {
  const q = version ? `?version=${version}` : "";
  try {
    return await call<PlanResponse>(`/plan/${pid(projectId)}${q}`, { signal });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function savePlan(projectId: string, artifactId: string, baseVersion: number, graph: TaskGraph): Promise<PlanResponse> {
  return call<PlanResponse>(`/plan/${pid(projectId)}`, {
    method: "PUT",
    body: JSON.stringify({ artifact_id: artifactId, base_version: baseVersion, graph }),
  });
}

export function decidePlan(projectId: string, approved: boolean, graphVersion: number, comment?: string): Promise<PlanResponse> {
  return call<PlanResponse>(`/plan/${pid(projectId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved, graph_version: graphVersion, comment: comment || null }),
  });
}

export function replan(projectId: string, feedback: string, failed: string[] = []): Promise<{ task_id: string; base_version: number }> {
  return call(`/plan/${pid(projectId)}/replan`, { method: "POST", body: JSON.stringify({ feedback, failed }) });
}

export function getCapabilities(signal?: AbortSignal): Promise<Capabilities> {
  return call<Capabilities>("/capabilities", { signal });
}

export function roadmapUrl(projectId: string): string {
  return `${BASE}/plan/${pid(projectId)}/roadmap.md`;
}
