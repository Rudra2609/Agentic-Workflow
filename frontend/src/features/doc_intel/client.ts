/**
 * Client for the doc_intel API (`/api/doc_intel/...`, mounted by the backend plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { DocumentModel, RequirementSet, RequirementsResponse } from "./types";

const BASE = `${API_URL}/api/doc_intel`;

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
    throw new ApiError(describeErrorBody(body, `Request failed (${res.status})`), {
      kind: "http", status: res.status, path, detail: body,
    });
  }
  return body as T;
}

/** The newest requirements of a project, or `null` before any were extracted. */
export async function getRequirements(projectId: string, signal?: AbortSignal,
                                      version?: number): Promise<RequirementsResponse | null> {
  const q = version ? `?version=${version}` : "";
  try {
    return await call<RequirementsResponse>(`/requirements/${encodeURIComponent(projectId)}${q}`, { signal });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function saveRequirements(projectId: string, artifactId: string, baseVersion: number,
                                 requirementSet: RequirementSet): Promise<RequirementsResponse> {
  return call<RequirementsResponse>(`/requirements/${encodeURIComponent(projectId)}`, {
    method: "PUT",
    body: JSON.stringify({ artifact_id: artifactId, base_version: baseVersion, requirement_set: requirementSet }),
  });
}

export function getDocumentModel(projectId: string, signal?: AbortSignal): Promise<DocumentModel> {
  return call<DocumentModel>(`/document-model/${encodeURIComponent(projectId)}`, { signal });
}

export function pageImageUrl(projectId: string, docId: string, page: number): string {
  return `${BASE}/pages/${encodeURIComponent(projectId)}/${encodeURIComponent(docId)}/${page}`;
}
