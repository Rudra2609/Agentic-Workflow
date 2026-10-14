/**
 * Client for the refinement API (`/api/refine/...`, mounted by Member 4's plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { DiffChange, Policy, RefineRun, RunSummary } from "./types";

const BASE = `${API_URL}/api/refine`;

async function call<T>(path: string, init: RequestInit & { signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.method && init.method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store", credentials: API_URL ? "include" : "same-origin" });
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
    throw new ApiError(describeErrorBody(body, `Request failed (${res.status})`), { kind: "http", status: res.status, path, detail: body });
  }
  return body as T;
}

const enc = encodeURIComponent;

export function listRuns(projectId: string, signal?: AbortSignal): Promise<RunSummary[]> {
  return call<RunSummary[]>(`/runs/${enc(projectId)}`, { signal });
}

export function getRun(projectId: string, runId: string, signal?: AbortSignal): Promise<RefineRun> {
  return call<RefineRun>(`/runs/${enc(projectId)}/${enc(runId)}`, { signal });
}

export function getDiff(projectId: string, runId: string, a: number, b: number, signal?: AbortSignal): Promise<{ changes: DiffChange[] }> {
  return call(`/runs/${enc(projectId)}/${enc(runId)}/diff?a=${a}&b=${b}`, { signal });
}

export function getOutput(projectId: string, runId: string, index: number, signal?: AbortSignal): Promise<unknown> {
  return call(`/runs/${enc(projectId)}/${enc(runId)}/outputs/${index}`, { signal });
}

export function checkAgain(projectId: string, artifactId: string): Promise<{ task_id: string; version: number }> {
  return call(`/runs/${enc(projectId)}`, { method: "POST", body: JSON.stringify({ artifact_id: artifactId }) });
}

export function getPolicy(signal?: AbortSignal): Promise<Policy> {
  return call<Policy>("/policy", { signal });
}
