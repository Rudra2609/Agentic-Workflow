/**
 * Client for the verify API (`/api/verify/...`, mounted by Member 6's plug-in) and the saved-page endpoint of the
 * research API (Member 5's, read only). Same rules as the core client (`@/lib/api`): session cookie, CSRF header
 * on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { PageView, RunDetail, RunSummary } from "./types";

async function call<T>(path: string, init: RequestInit & { signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.method && init.method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api${path}`, { ...init, headers, cache: "no-store", credentials: API_URL ? "include" : "same-origin" });
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
  return call<RunSummary[]>(`/verify/runs/${enc(projectId)}`, { signal });
}

export function getRun(projectId: string, taskId: string, signal?: AbortSignal): Promise<RunDetail> {
  return call<RunDetail>(`/verify/runs/${enc(projectId)}/${enc(taskId)}`, { signal });
}

export function requestFollowUp(projectId: string, taskId: string, claimIds: string[]): Promise<{ research_task_id: string; verify_task_id: string }> {
  return call(`/verify/runs/${enc(projectId)}/${enc(taskId)}/follow-up`, { method: "POST", body: JSON.stringify({ claim_ids: claimIds }) });
}

/** The cleaned page a quote was checked against (Member 5's endpoint; `researchTaskId` gives the quote spans). */
export function getPage(projectId: string, artifactId: string, researchTaskId: string, signal?: AbortSignal): Promise<PageView> {
  return call<PageView>(`/research/pages/${enc(projectId)}/${enc(artifactId)}?task_id=${enc(researchTaskId)}`, { signal });
}
