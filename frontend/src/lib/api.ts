declare global {
  interface Window {
    // Runtime backend URL injected server-side from process.env.API_URL so a
    // single image can be deployed anywhere without a rebuild. Empty string
    // means same-origin (Caddy) mode.
    __PT_API_URL__?: string;
    // Runtime API path prefix injected server-side from process.env.API_PREFIX.
    __PT_API_PREFIX__?: string;
  }
}

// Resolve the backend base URL at call time: on the client prefer the runtime
// override injected by the server; on the server read API_URL at request time.
// A localhost default covers local dev.
export function getApiBaseUrl(): string {
  if (
    typeof window !== "undefined" &&
    typeof window.__PT_API_URL__ === "string"
  ) {
    return window.__PT_API_URL__;
  }
  return process.env.API_URL?.trim() || "http://localhost:8010";
}

// Resolve the API path prefix at call time: on the client prefer the runtime
// override injected by the server; on the server read API_PREFIX at request
// time.
export function getApiPrefix(): string {
  if (
    typeof window !== "undefined" &&
    typeof window.__PT_API_PREFIX__ === "string"
  ) {
    return window.__PT_API_PREFIX__;
  }
  return process.env.API_PREFIX?.trim() || "";
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

// A 401 on this path is an expected outcome (bad credentials), not a
// sign of an expired session, so it must not trigger auto-logout.
const AUTH_401_EXEMPT_PATHS = [
  "/auth/login",
  "/auth/logout",
  "/auth/passkeys/login/options",
  "/auth/passkeys/login/verify",
];

type SessionExpiredHandler = () => void;
let sessionExpiredHandler: SessionExpiredHandler | null = null;

// AuthProvider registers itself here on mount so this module (which has no
// access to React context or the router) can notify it of an expired session.
export function setSessionExpiredHandler(handler: SessionExpiredHandler | null): void {
  sessionExpiredHandler = handler;
}

export async function extractApiError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => ({}));
  const detail = (body as { detail?: unknown }).detail;
  const message = Array.isArray(detail)
    ? detail.map((e: { msg?: string }) => e.msg ?? String(e)).join("; ")
    : (detail ?? `Request failed with status ${res.status}`);
  return new Error(String(message));
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(init?.headers ?? {}),
  };

  // credentials: "include" sends the HttpOnly access_token cookie automatically.
  const res = await fetch(`${getApiBaseUrl()}${getApiPrefix()}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!res.ok) {
    if (res.status === 401 && !AUTH_401_EXEMPT_PATHS.includes(path)) {
      sessionExpiredHandler?.();
      throw new SessionExpiredError();
    }
    throw await extractApiError(res);
  }

  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}
