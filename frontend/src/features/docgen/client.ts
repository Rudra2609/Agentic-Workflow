/**
 * Client for the documentation API (`/api/docgen/...`, mounted by Member 9's plug-in). Same rules as the core
 * client (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { BundleDetail, BundleSummary, CheckResult } from "./types";

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

export function listBundles(
  projectId: string,
  signal?: AbortSignal,
): Promise<BundleSummary[]> {
  return call<BundleSummary[]>(`/docgen/bundles/${enc(projectId)}`, {
    signal,
  });
}

export function getBundle(
  projectId: string,
  taskId: string,
  signal?: AbortSignal,
): Promise<BundleDetail> {
  return call<BundleDetail>(
    `/docgen/bundles/${enc(projectId)}/${enc(taskId)}`,
    { signal },
  );
}

export function regenerate(
  projectId: string,
  taskId: string,
): Promise<{ task_id: string }> {
  return call(`/docgen/bundles/${enc(projectId)}/${enc(taskId)}/regenerate`, {
    method: "POST",
    body: "{}",
  });
}

export function checkMarkdown(
  projectId: string,
  markdown: string,
  taskId?: string,
): Promise<CheckResult> {
  return call<CheckResult>(`/docgen/check/${enc(projectId)}`, {
    method: "POST",
    body: JSON.stringify({ markdown, task_id: taskId ?? null }),
  });
}

export function exportUrl(
  projectId: string,
  taskId: string,
  name: "architecture.svg" | "site.html" | "docstrings.diff",
): string {
  return `${API_URL}/api/docgen/bundles/${enc(projectId)}/${enc(taskId)}/${name}`;
}

export function fileUrl(
  projectId: string,
  taskId: string,
  name: string,
): string {
  return `${API_URL}/api/docgen/bundles/${enc(projectId)}/${enc(taskId)}/files/${enc(name)}`;
}
