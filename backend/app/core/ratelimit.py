import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.deps import current_user
from app.models.user import User

# In-memory sliding-window rate limiter. Single uvicorn process only;
# limits are read from `settings` at REQUEST time so tests can tune them.
_WINDOWS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_WINDOW_SECONDS: dict[tuple[str, str], int] = {}


def _sweep_expired(now: float) -> None:
    """Evict buckets whose timestamps have all aged out.

    Keys include attacker-influenced values (account emails), so the map
    would otherwise grow without bound. A full sweep per check is fine at
    this app's scale.
    """
    for bucket in list(_WINDOWS.keys()):
        window = _WINDOWS[bucket]
        window_seconds = _WINDOW_SECONDS.get(bucket, 0)
        while window and window[0] <= now - window_seconds:
            window.popleft()
        if not window:
            del _WINDOWS[bucket]
            _WINDOW_SECONDS.pop(bucket, None)


def _is_allowed(scope: str, key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    _sweep_expired(now)
    _WINDOW_SECONDS[(scope, key)] = window_seconds
    window = _WINDOWS[(scope, key)]
    while window and window[0] <= now - window_seconds:
        window.popleft()
    if len(window) < limit:
        window.append(now)
        return True
    return False


def reset_rate_limits(scope: str | None = None) -> None:
    """Clear one scope's buckets, or all buckets when scope is None (test helper)."""
    if scope is None:
        _WINDOWS.clear()
        _WINDOW_SECONDS.clear()
        return
    for key in list(_WINDOWS.keys()):
        if key[0] == scope:
            del _WINDOWS[key]
            _WINDOW_SECONDS.pop(key, None)


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # A single trusted reverse proxy appends the address it observed to
            # any header the client sent, so the RIGHTMOST entry is the real
            # client. Leftmost entries are attacker-controlled and must not be
            # trusted for rate-limit keys.
            return forwarded.split(",")[-1].strip()
    # When running behind the built-in Next proxy (127.0.0.1), trust the
    # X-Real-IP header it injects from its own view of the client. Only the
    # loopback peer can reach uvicorn in the container, so this cannot be
    # spoofed by external clients.
    if request.client is not None and request.client.host in {"127.0.0.1", "::1"}:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


def rate_limited_key(scope: str, key: str, limit: int, window_seconds: int) -> None:
    """Count a request against a caller-supplied key (e.g. a login email)."""
    if not _is_allowed(scope, f"key:{key}", limit, window_seconds):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
        )


def rate_limited(scope: str) -> Callable[..., None]:
    def dependency(request: Request) -> None:
        limit = getattr(settings, f"{scope}_rate_limit")
        window_seconds = getattr(settings, f"{scope}_rate_window_seconds")
        if not _is_allowed(scope, client_ip(request), limit, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
            )

    return dependency


def rate_limited_by_user(scope: str) -> Callable[..., None]:
    def dependency(user: User = Depends(current_user)) -> None:
        limit = getattr(settings, f"{scope}_rate_limit")
        window_seconds = getattr(settings, f"{scope}_rate_window_seconds")
        if not _is_allowed(scope, f"user:{user.id}", limit, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
            )

    return dependency
