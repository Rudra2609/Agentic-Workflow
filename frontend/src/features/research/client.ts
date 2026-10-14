/**
 * Client for the research API (`/api/research/...`, mounted by Member 5's plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { PageView, Providers, RunDetail, RunSummary } from "./types";

const BASE = `${API_URL}/api/research`;

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

export function getRun(projectId: string, taskId: string, signal?: AbortSignal): Promise<RunDetail> {
  return call<RunDetail>(`/runs/${enc(projectId)}/${enc(taskId)}`, { signal });
}

export function getPage(projectId: string, artifactId: string, taskId: string, signal?: AbortSignal): Promise<PageView> {
  return call<PageView>(`/pages/${enc(projectId)}/${enc(artifactId)}?task_id=${enc(taskId)}`, { signal });
}

export function startResearch(projectId: string, questions: string[]): Promise<{ task_id: string }> {
  return call(`/runs/${enc(projectId)}`, { method: "POST", body: JSON.stringify({ questions }) });
}

export function getProviders(signal?: AbortSignal): Promise<Providers> {
  return call<Providers>("/providers", { signal });
}
