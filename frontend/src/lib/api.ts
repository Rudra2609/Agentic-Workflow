/**
 * Typed client for the hmap FastAPI backend (all routes live under `/api`).
 *
 * Every failure is an {@link ApiError} with a human-readable `message`:
 *  - `kind: "http"`    the API answered with 4xx/5xx; `message` is FastAPI's `detail` (validation errors joined)
 *  - `kind: "network"` the API could not be reached (not running, wrong NEXT_PUBLIC_API_URL, CORS, timeout)
 *  - `kind: "parse"`   the API answered 2xx with something that is not JSON
 *
 * Requests carry the session cookie (same origin via the Next.js proxy) and, for anything that changes state, the
 * `X-CSRF-Token` header copied from the `hmap_csrf` cookie. A 401 dispatches `hmap:unauthorized` on `window` so the
 * app can send the user to the sign-in page.
 */
import { API_URL, BACKEND_START_HINT, normalizeBaseUrl } from "./config";
import type {
  Agent,
  ArtifactItem,
  CancelResult,
  CapabilityRow,
  DeadLetter,
  Health,
  HmapEvent,
  Me,
  NewTask,
  Project,
  StopResult,
  Task,
  TaskDetail,
  UploadResult,
} from "./types";

export type ApiErrorKind = "http" | "network" | "parse";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly path: string;
  readonly detail: unknown;

  constructor(
    message: string,
    opts: { kind: ApiErrorKind; status?: number | null; path: string; detail?: unknown; cause?: unknown },
  ) {
    super(message, opts.cause === undefined ? undefined : { cause: opts.cause });
    this.name = "ApiError";
    this.kind = opts.kind;
    this.status = opts.status ?? null;
    this.path = opts.path;
    this.detail = opts.detail;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** The form field a validation error belongs to (accounts API: `{"detail": {"message", "field"}}`). */
  get field(): string | null {
    const d = this.detail as { detail?: { field?: unknown } } | undefined;
    return typeof d?.detail?.field === "string" ? d.detail.field : null;
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

/** Turn a FastAPI error body into one readable line. */
export function describeErrorBody(body: unknown, fallback: string): string {
  if (typeof body === "string" && body.trim()) return body.trim();
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
      return (detail as { message: string }).message;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI/Pydantic 422: [{loc: ["body", "name"], msg: "Field required", ...}]
      return detail
        .map((d) => {
          if (d && typeof d === "object") {
            const item = d as { loc?: unknown; msg?: unknown };
            const loc = Array.isArray(item.loc) ? item.loc.filter((p) => p !== "body").join(".") : "";
            const msg = typeof item.msg === "string" ? item.msg : JSON.stringify(d);
            return loc ? `${loc}: ${msg}` : msg;
          }
          return String(d);
        })
        .join("; ");
    }
    if (detail != null) return JSON.stringify(detail);
  }
  return fallback;
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
  /** Per-request timeout; uploads get 4x this. Default 15 s. */
  timeoutMs?: number;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  json?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface EventQuery {
  projectId?: string | null;
  afterSeq?: number;
  limit?: number;
}

export const UNAUTHORIZED_EVENT = "hmap:unauthorized";

/** The CSRF token the API set as a readable cookie (double-submit). */
export function csrfToken(cookie: string = typeof document === "undefined" ? "" : document.cookie): string {
  for (const part of cookie.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === "hmap_csrf") return decodeURIComponent(v.join("="));
  }
  return "";
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = normalizeBaseUrl(options.baseUrl ?? API_URL);
  const timeoutMs = options.timeoutMs ?? 15_000;
  const doFetch: typeof fetch = options.fetch ?? ((...args) => globalThis.fetch(...args));

  function url(path: string, query?: RequestOptions["query"]): string {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
    }
    const qs = params.toString();
    return `${baseUrl}/api${path}${qs ? `?${qs}` : ""}`;
  }

  async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const controller = new AbortController();
    const limit = opts.timeoutMs ?? timeoutMs;
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, limit);
    const onAbort = () => controller.abort();
    opts.signal?.addEventListener("abort", onAbort, { once: true });

    const method = opts.method ?? "GET";
    const headers: Record<string, string> = { Accept: "application/json" };
    if (method !== "GET") {
      const csrf = csrfToken();
      if (csrf) headers["X-CSRF-Token"] = csrf;
    }
    let body: BodyInit | undefined;
    if (opts.form) {
      body = opts.form; // the browser sets the multipart boundary
    } else if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.json);
    }

    let res: Response;
    try {
      res = await doFetch(url(path, opts.query), {
        method,
        headers,
        body,
        signal: controller.signal,
        cache: "no-store",
        credentials: baseUrl ? "include" : "same-origin",
      });
    } catch (cause) {
      if (opts.signal?.aborted) throw cause; // caller cancelled: let it propagate untouched
      const why = timedOut ? `timed out after ${Math.round(limit / 1000)} s` : "is not reachable";
      throw new ApiError(
        `The hmap API at ${baseUrl || "/api"} ${why}. Is the backend running? Start it with: ${BACKEND_START_HINT}`,
        { kind: "network", path, cause },
      );
    } finally {
      clearTimeout(timer);
      opts.signal?.removeEventListener("abort", onAbort);
    }

    const text = await res.text();
    let parsed: unknown = undefined;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    if (res.status === 204) return undefined as T;
    if (!res.ok) {
      const fallback = `${res.status} ${res.statusText || "error"}`.trim();
      throw new ApiError(describeErrorBody(parsed, fallback), {
        kind: "http",
        status: res.status,
        path,
        detail: parsed,
      });
    }
    if (typeof parsed === "string") {
      throw new ApiError(`Unexpected non-JSON response from ${path}`, {
        kind: "parse",
        status: res.status,
        path,
        detail: parsed,
      });
    }
    return parsed as T;
  }

  return {
    baseUrl,

    health: (signal?: AbortSignal) => request<Health>("/health", { signal, timeoutMs: 5_000 }),
    /** Gateway mode and the team key pool by key fingerprint (empty without keys). */
    llmUsage: (signal?: AbortSignal) => request<{ mode: string; cloud_keys: Record<string, unknown> }>("/llm/usage", { signal }),

    listProjects: (signal?: AbortSignal, query: { q?: string; archived?: boolean } = {}) =>
      request<Project[]>("/projects", { signal, query: { q: query.q, archived: query.archived || undefined } }),
    createProject: (name: string, autoApprove = false, goal?: string, cloudOk = true) =>
      request<Project>("/projects", {
        method: "POST",
        json: { name, auto_approve: autoApprove, goal: goal?.trim() ? goal.trim() : null, cloud_ok: cloudOk },
      }),
    updateProject: (projectId: string, patch: { name?: string; archived?: boolean; cloud_ok?: boolean }) =>
      request<Project>(`/projects/${encodeURIComponent(projectId)}`, { method: "PATCH", json: patch }),
    deleteProject: (projectId: string) =>
      request<{ deleted: boolean; files_erased: number }>(`/projects/${encodeURIComponent(projectId)}`, {
        method: "DELETE",
      }),
    startRun: (projectId: string, goal: string) =>
      request<Project>(`/projects/${encodeURIComponent(projectId)}/runs`, { method: "POST", json: { goal } }),
    stopProject: (projectId: string, reason = "stopped by user") =>
      request<StopResult>(`/projects/${encodeURIComponent(projectId)}/stop`, { method: "POST", json: { reason } }),
    listArtifacts: (projectId: string, signal?: AbortSignal) =>
      request<ArtifactItem[]>(`/projects/${encodeURIComponent(projectId)}/artifacts`, { signal }),
    artifactUrl: (projectId: string, artifactId: string, version?: number, download = false) =>
      url(`/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`, {
        version,
        download: download || undefined,
      }),
    /** The artifact's text (JSON/text previews); size-limited by the caller's choice of what to preview. */
    artifactText: async (projectId: string, artifactId: string, version?: number, signal?: AbortSignal) => {
      const res = await doFetch(
        url(`/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`, { version }),
        { signal, credentials: baseUrl ? "include" : "same-origin", cache: "no-store" },
      );
      if (!res.ok) throw new ApiError(`Could not load the file (${res.status})`, { kind: "http", status: res.status, path: "/artifacts" });
      return res.text();
    },
    getProject: (projectId: string, signal?: AbortSignal) =>
      request<Project>(`/projects/${encodeURIComponent(projectId)}`, { signal }),
    listTasks: (projectId: string, signal?: AbortSignal) =>
      request<Task[]>(`/projects/${encodeURIComponent(projectId)}/tasks`, { signal }),
    uploadDocument: (projectId: string, file: File | Blob, filename?: string) => {
      const form = new FormData();
      if (filename !== undefined) form.append("file", file, filename);
      else form.append("file", file);
      return request<UploadResult>(`/projects/${encodeURIComponent(projectId)}/documents`, {
        method: "POST",
        form,
        timeoutMs: timeoutMs * 4,
      });
    },
    /** Several documents as ONE run; `path` keeps each file's folder ("Part A/brief.pdf"). */
    uploadDocuments: (projectId: string, docs: ReadonlyArray<{ file: File | Blob; path: string }>) => {
      const form = new FormData();
      for (const d of docs) {
        form.append("files", d.file, d.path.split("/").pop() || "document");
        form.append("paths", d.path);
      }
      return request<UploadResult>(`/projects/${encodeURIComponent(projectId)}/documents`, {
        method: "POST",
        form,
        timeoutMs: timeoutMs * 8,
      });
    },
    submitPlan: (projectId: string, graph: unknown, requireApproval = true) =>
      request<Project>(`/projects/${encodeURIComponent(projectId)}/plan`, {
        method: "POST",
        json: graph,
        query: { require_approval: requireApproval },
      }),
    decideApproval: (projectId: string, approved: boolean, comment?: string | null) =>
      request<Project>(`/projects/${encodeURIComponent(projectId)}/approval`, {
        method: "POST",
        json: { approved, comment: comment?.trim() ? comment.trim() : null },
      }),
    createTask: (projectId: string, task: NewTask) =>
      request<TaskDetail>(`/projects/${encodeURIComponent(projectId)}/tasks`, { method: "POST", json: task }),

    getTask: (taskId: string, signal?: AbortSignal) =>
      request<TaskDetail>(`/tasks/${encodeURIComponent(taskId)}`, { signal }),
    cancelTask: (taskId: string, reason = "cancelled by user") =>
      request<CancelResult>(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST", json: { reason } }),

    listAgents: (signal?: AbortSignal) => request<Agent[]>("/agents", { signal }),
    listCapabilities: (signal?: AbortSignal) => request<CapabilityRow[]>("/agents/capabilities", { signal }),
    listEvents: (query: EventQuery = {}, signal?: AbortSignal) =>
      request<HmapEvent[]>("/events", {
        signal,
        query: { project_id: query.projectId ?? undefined, after_seq: query.afterSeq ?? 0, limit: query.limit },
      }),
    listDeadLetters: (signal?: AbortSignal) => request<DeadLetter[]>("/dead-letters", { signal }),

    // ---- accounts
    me: (signal?: AbortSignal) => request<Me>("/auth/me", { signal }),
    register: (name: string, email: string, password: string) =>
      request<Me>("/auth/register", { method: "POST", json: { name, email, password } }),
    login: (email: string, password: string) =>
      request<Me>("/auth/login", { method: "POST", json: { email, password } }),
    logout: () => request<void>("/auth/logout", { method: "POST" }),
    logoutEverywhere: () => request<void>("/auth/logout-all", { method: "POST" }),
    updateProfile: (name: string) => request<Me>("/auth/me", { method: "PATCH", json: { name } }),
    changePassword: (currentPassword: string, newPassword: string) =>
      request<{ other_sessions_ended: number }>("/auth/password", {
        method: "POST",
        json: { current_password: currentPassword, new_password: newPassword },
      }),
    forgotPassword: (email: string) =>
      request<{ message: string }>("/auth/forgot", { method: "POST", json: { email } }),
    resetPassword: (token: string, password: string) =>
      request<void>("/auth/reset", { method: "POST", json: { token, password } }),
    wsTicket: () => request<{ ticket: string }>("/auth/ws-ticket", { method: "POST" }),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** The app-wide client (same origin through the Next.js proxy, or NEXT_PUBLIC_API_URL). */
export const api: ApiClient = createApiClient();

/** Human-readable message for anything thrown by the client (or elsewhere). */
export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return typeof err === "string" ? err : "Unexpected error";
}
