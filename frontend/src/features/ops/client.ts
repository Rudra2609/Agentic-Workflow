/**
 * Client for the operations API (`/api/ops/...`, mounted by Member 4's plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { BusDeadLetter, Explanation, Overview, TaskRow } from "./types";

const BASE = `${API_URL}/api/ops`;

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

export const getOverview = (signal?: AbortSignal) => call<Overview>("/overview", { signal });
export const getFailures = (signal?: AbortSignal) => call<TaskRow[]>("/failures", { signal });
export const getDeadLetters = (signal?: AbortSignal) => call<{ tasks: TaskRow[]; messages: BusDeadLetter[] }>("/dlq", { signal });
export const explainTask = (taskId: string, signal?: AbortSignal) =>
  call<Explanation>(`/explain/${encodeURIComponent(taskId)}`, { signal });
export const replayTask = (taskId: string, reason: string) =>
  call<{ task_id: string; replay: number; unblocked: string[]; state: string; executions: number }>(
    `/replay/${encodeURIComponent(taskId)}`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );
