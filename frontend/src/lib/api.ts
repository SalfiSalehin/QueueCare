import type { ApiErrorBody } from "@/types/api";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
    public readonly details?: Record<string, string>[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1").replace(/\/$/, "");
const CSRF_COOKIE = "qc_csrf";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// Auth endpoints that must never trigger a refresh-and-retry (it would loop or hide a real failure).
const NO_REFRESH = ["/auth/login", "/auth/register", "/auth/refresh", "/auth/forgot-password", "/auth/reset-password", "/auth/verify-email"];

export function readCookie(name: string, source?: string): string | undefined {
  const raw = source ?? (typeof document === "undefined" ? "" : document.cookie);
  for (const part of raw.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

export function buildUrl(path: string, query?: Record<string, string | number | boolean | undefined | null>): string {
  const url = `${BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function parseError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | undefined;
  try {
    body = (await res.json()) as Partial<ApiErrorBody>;
  } catch {
    body = undefined;
  }
  const e = body?.error;
  return new ApiError(res.status, e?.code ?? "error", e?.message ?? `Request failed (${res.status})`, e?.request_id, e?.details);
}

let refreshing: Promise<boolean> | null = null;

/** One refresh at a time, shared by every request that hits a 401 at the same moment. */
function refreshOnce(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const csrf = readCookie(CSRF_COOKIE);
      const res = await fetch(buildUrl("/auth/refresh"), {
        method: "POST", credentials: "include", cache: "no-store",
        headers: csrf ? { "X-CSRF-Token": csrf } : {},
      });
      return res.ok;
    } catch {
      return false;
    } finally {
      setTimeout(() => { refreshing = null; }, 0);
    }
  })();
  return refreshing;
}

export interface RequestOptions {
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const res = await fetch(buildUrl(path, opts.query), {
    method, headers, credentials: "include", cache: "no-store", signal: opts.signal,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (res.status === 401 && !retried && !NO_REFRESH.includes(path)) {
    if (await refreshOnce()) return request<T>(method, path, opts, true);
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  del: <T>(path: string) => request<T>("DELETE", path),
};
