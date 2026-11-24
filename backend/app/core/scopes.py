"""Permission scopes for family members and API keys."""

from __future__ import annotations

ALL_SCOPES: tuple[str, ...] = (
    "bills:read",
    "bills:write",
    "payments:write",
    "imports:read",
    "imports:write",
    "export:write",
)

ALL_SCOPES_SET: frozenset[str] = frozenset(ALL_SCOPES)

VIEWER_SCOPES: tuple[str, ...] = ("bills:read", "imports:read")
CONTRIBUTOR_SCOPES: tuple[str, ...] = (
    "bills:read",
    "bills:write",
    "payments:write",
    "imports:read",
    "imports:write",
)
ADMIN_SCOPES: tuple[str, ...] = ALL_SCOPES


def validate_scopes(scopes: list[str]) -> list[str]:
    """Normalize, deduplicate, and validate scope strings against ALL_SCOPES."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in scopes:
        s = raw.strip()
        if not s:
            continue
        if s not in ALL_SCOPES_SET:
            raise ValueError(f"Unknown scope: {s}")
        if s not in seen:
            seen.add(s)
            cleaned.append(s)
    if not cleaned:
        raise ValueError("At least one permission scope is required")
    return cleaned
