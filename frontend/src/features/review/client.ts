/**
 * Client for the review API (`/api/review/...`, mounted by Member 10's plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { Decision, ReportDetail, Rounds, Verdict } from "./types";

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

export function listRounds(projectId: string, signal?: AbortSignal): Promise<Rounds> {
  return call<Rounds>(`/review/reports/${enc(projectId)}`, { signal });
}

export function getReport(
  projectId: string,
  taskId: string,
  signal?: AbortSignal,
): Promise<ReportDetail> {
  return call<ReportDetail>(`/review/reports/${enc(projectId)}/${enc(taskId)}`, { signal });
}

export function overrideItem(
  projectId: string,
  taskId: string,
  itemId: string,
  verdict: Verdict,
  note: string,
): Promise<{ decision: Decision }> {
  return call(`/review/reports/${enc(projectId)}/${enc(taskId)}/override`, {
    method: "POST",
    body: JSON.stringify({ item_id: itemId, verdict, note }),
  });
}

export function acceptReport(
  projectId: string,
  taskId: string,
  notes: string,
): Promise<{ decision: Decision; project_state: string }> {
  return call(`/review/reports/${enc(projectId)}/${enc(taskId)}/accept`, {
    method: "POST",
    body: JSON.stringify({ notes }),
  });
}

export function requestChanges(
  projectId: string,
  taskId: string,
  text: string,
  step: string | null,
): Promise<{ created: string[] }> {
  return call(`/review/reports/${enc(projectId)}/${enc(taskId)}/request-changes`, {
    method: "POST",
    body: JSON.stringify({ text, task_id: step }),
  });
}
