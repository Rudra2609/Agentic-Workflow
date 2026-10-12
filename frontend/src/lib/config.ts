/**
 * Where the backend is.
 *
 * REST: same origin. The Next.js server proxies `/api/*` to the FastAPI backend (`HMAP_API_ORIGIN`, see
 * next.config.ts), so the session cookie is first-party and no CORS is involved. `NEXT_PUBLIC_API_URL` may point the
 * browser straight at the API instead (then that API must list this site in its allowed origins).
 *
 * WebSocket: proxies do not forward WebSocket upgrades reliably, so the live feed connects to the API directly with
 * a single-use ticket: `NEXT_PUBLIC_WS_URL`, or the page's host on port 8000.
 */
export const DEFAULT_API_URL = "";

export function normalizeBaseUrl(url: string | undefined | null): string {
  return (url ?? "").trim().replace(/\/+$/, "");
}

export const API_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL);

/** http://host:8000 -> ws://host:8000, https -> wss. */
export function toWebSocketUrl(httpUrl: string): string {
  return normalizeBaseUrl(httpUrl).replace(/^http(s?):\/\//i, (_m, s: string) => `ws${s}://`);
}

/** Base URL for the live-event WebSocket (no trailing slash). */
export function webSocketBase(): string {
  const configured = normalizeBaseUrl(process.env.NEXT_PUBLIC_WS_URL);
  if (configured) return toWebSocketUrl(configured);
  if (API_URL) return toWebSocketUrl(API_URL);
  if (typeof window === "undefined") return "ws://127.0.0.1:8000";
  const secure = window.location.protocol === "https:";
  return `${secure ? "wss" : "ws"}://${window.location.hostname}:8000`;
}

/** The command a developer runs when the API is down (shown in developer-mode error details). */
export const BACKEND_START_HINT =
  "cd backend && HMAP_LLM_MODE=fake uv run uvicorn hmap.api.app:create_app --factory --port 8000";
