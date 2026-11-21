/**
 * Client for the testing API (`/api/testing/...`, mounted by Member 8's plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { Quarantine, RunDetail, RunSummary } from "./types";

async function call<T>(
  path: string,
  init: RequestInit & { signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.method && init.method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api${path}`, {
      ...init,
      headers,
      cache: "no-store",
      credentials: API_URL ? "include" : "same-origin",
    });
  } catch (cause) {
    if (init.signal?.aborted) throw cause;
    throw new ApiError("The HMAP server is not reachable.", {
      kind: "network",
      path,
      cause,
    });
  }
  const text = await res.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    /* keep the text */
  }
  if (!res.ok) {
    throw new ApiError(
      describeErrorBody(body, `Request failed (${res.status})`),
      { kind: "http", status: res.status, path, detail: body },
    );
  }
  return body as T;
}

const enc = encodeURIComponent;

export function listRuns(
  projectId: string,
  signal?: AbortSignal,
): Promise<RunSummary[]> {
  return call<RunSummary[]>(`/testing/runs/${enc(projectId)}`, { signal });
}

export function getRun(
  projectId: string,
  taskId: string,
  signal?: AbortSignal,
): Promise<RunDetail> {
  return call<RunDetail>(`/testing/runs/${enc(projectId)}/${enc(taskId)}`, {
    signal,
  });
}

export function rerun(
  projectId: string,
  taskId: string,
): Promise<{ task_id: string }> {
  return call(`/testing/runs/${enc(projectId)}/${enc(taskId)}/rerun`, {
    method: "POST",
  });
}

export function logUrl(projectId: string, taskId: string): string {
  return `${API_URL}/api/testing/runs/${enc(projectId)}/${enc(taskId)}/log`;
}

export function getQuarantine(
  projectId: string,
  signal?: AbortSignal,
): Promise<Quarantine> {
  return call<Quarantine>(`/testing/quarantine/${enc(projectId)}`, { signal });
}

export function releaseTest(
  projectId: string,
  test: string,
): Promise<Quarantine> {
  return call(`/testing/quarantine/${enc(projectId)}/release`, {
    method: "POST",
    body: JSON.stringify({ test }),
  });
}
