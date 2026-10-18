import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const publicRoutes = ["/login", "/register", "/forgot-password", "/reset-password"];

// Only page-navigation methods may be bounced to the GET-only /login page.
// Redirecting a POST/PUT/DELETE (e.g. Next's router or Server-Function calls)
// with a 307 preserves the method and produces a 405 on /login.
const NAVIGATION_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

// Hardening headers applied to every proxy response. The API origin is read at
// runtime (bracket access so the bundler cannot inline it) so the CSP
// connect-src matches whichever backend this container is pointed at.
function securityHeaders(nonce: string): Record<string, string> {
  const apiOrigin = process.env["API_URL"]?.trim() || "http://localhost:8010";
  const scriptSrc = `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${
    process.env.NODE_ENV !== "production" ? " 'unsafe-eval'" : ""
  }`;
  return {
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Content-Security-Policy": [
      "default-src 'self'",
      scriptSrc,
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      `connect-src 'self' ${apiOrigin}`,
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
    ].join("; "),
  };
}

function applySecurityHeaders(
  res: NextResponse,
  headers: Record<string, string>,
): NextResponse {
  for (const [key, value] of Object.entries(headers)) {
    res.headers.set(key, value);
  }
  return res;
}

// Decode the JWT payload (no signature check — just the exp claim) so routing
// decisions can tell a live cookie apart from a dead one. A signed-body
// verification would need the secret in this process; the backend is still the
// source of truth for actual auth, this only stops the login redirect loop.
function readTokenExp(token: string): number | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(b64)) as { exp?: unknown };
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

function clearAuthCookies(res: NextResponse): void {
  res.cookies.delete("access_token");
  res.cookies.delete("auth_logged_in");
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get("access_token")?.value;
  const method = request.method;

  const isPublicRoute = publicRoutes.some(
    (route) => pathname === route || pathname.startsWith(route + "/"),
  );

  // Fresh nonce per request. It is embedded in the CSP via the request headers
  // so Next can attach it to its own scripts, and is exposed to the app as
  // x-nonce for manually written inline scripts.
  const nonce = btoa(crypto.randomUUID());
  const headers = securityHeaders(nonce);

  // A present-but-dead cookie is not an authenticated session. Treat it as
  // logged out so /login is reachable, and strip it so it stops being honored.
  const nowSec = Math.floor(Date.now() / 1000);
  const tokenAlive = token !== undefined && (readTokenExp(token) ?? 0) > nowSec;

  if (!tokenAlive && !isPublicRoute) {
    if (!NAVIGATION_METHODS.has(method)) {
      // Not a navigation — fail it cleanly so it is never redirected onto
      // the login page. The router treats this as an auth failure and falls
      // back to a normal (GET) page navigation.
      const res = applySecurityHeaders(
        NextResponse.json({ error: "Unauthorized" }, { status: 401 }),
        headers,
      );
      if (token) clearAuthCookies(res);
      return res;
    }
    // Marks this as a session-expiry redirect (as opposed to a plain
    // unauthenticated visit) so the login page can show the "session
    // expired" banner even when no client-side 401 ever fired — this path
    // runs server-side, before React mounts, so it can't touch sessionStorage.
    const url = new URL("/login", request.url);
    url.searchParams.set("session_expired", "1");
    // 303 forces the follow-up request to be GET, guaranteeing the login
    // page is always reached by GET regardless of the original method.
    const res = applySecurityHeaders(
      NextResponse.redirect(url, { status: 303 }),
      headers,
    );
    if (token) clearAuthCookies(res);
    return res;
  }

  if (!NAVIGATION_METHODS.has(method) && isPublicRoute) {
    // A non-GET method reached a public page directly (e.g. a native form
    // submission before React attached preventDefault, or a client POST to
    // the current URL). The page has no method handler, so normalize to the
    // GET page instead of letting Next answer 405.
    const res = applySecurityHeaders(
      NextResponse.redirect(request.nextUrl, { status: 303 }),
      headers,
    );
    if (token && !tokenAlive) clearAuthCookies(res);
    return res;
  }

  if (tokenAlive && isPublicRoute) {
    return applySecurityHeaders(
      NextResponse.redirect(new URL("/dashboard", request.url), { status: 303 }),
      headers,
    );
  }

  // Serve the page. The request headers carry the nonce so Next can attach it
  // to its framework and page scripts during rendering. If a dead cookie rode
  // along, clear it so the next public route visit doesn't bounce to
  // /dashboard on a session that no longer exists.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set(
    "Content-Security-Policy",
    headers["Content-Security-Policy"],
  );
  const res = applySecurityHeaders(
    NextResponse.next({ request: { headers: requestHeaders } }),
    headers,
  );
  if (token && !tokenAlive) clearAuthCookies(res);
  return res;
}

export const config = {
  matcher: [
    // /api/* is handled by the next.config rewrite (proxied straight to the
    // backend), so it must bypass the auth/CSP proxy entirely.
    "/((?!api/|_next/static|_next/image|favicon.ico|manifest\\.webmanifest$|sw\\.js$|icon-(?:192|512)\\.png$|platybill-logo(?:-light)?\\.(?:png|svg)$).*)",
  ],
};
