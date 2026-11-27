/**
 * Client for the models API (`/api/models/...`, mounted by Member 11's plug-in). Same rules as the core client
 * (`@/lib/api`): session cookie, CSRF header on writes, errors as {@link ApiError} with a readable message.
 */
import { ApiError, csrfToken, describeErrorBody } from "@/lib/api";
import { API_URL } from "@/lib/config";

import type { Bench, FineTune, Hardware, Registry, Routes } from "./types";

async function call<T>(path: string, init: RequestInit & { signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.method && init.method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/models${path}`, {
      ...init,
      headers,
      cache: "no-store",
      credentials: API_URL ? "include" : "same-origin",
    });
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
      kind: "http",
      status: res.status,
      path,
      detail: body,
    });
  }
  return body as T;
}

export const getRegistry = (signal?: AbortSignal) => call<Registry>("/registry", { signal });
export const syncRegistry = () => call<Registry>("/registry/sync", { method: "POST" });
export const setModelFlag = (id: string, action: "pin" | "disable" | "enable") =>
  call<Record<string, unknown>>(`/registry/${encodeURIComponent(id)}/${action}`, { method: "POST" });
export const pullModel = (model: string) =>
  call<{ started: boolean; command: string; why?: string }>("/pull", { method: "POST", body: JSON.stringify({ model }) });
export const getHardware = (signal?: AbortSignal) => call<Hardware>("/hardware", { signal });
export const getRoutes = (signal?: AbortSignal) => call<Routes>("/routes?limit=100", { signal });
export const getBench = (signal?: AbortSignal) => call<Bench>("/bench", { signal });
export const getFineTune = (signal?: AbortSignal) => call<FineTune>("/finetune", { signal });
