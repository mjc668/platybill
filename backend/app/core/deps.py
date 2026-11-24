from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.scopes import ALL_SCOPES_SET
from app.core.security import decode_token
from app.models.api_key import ApiKey
from app.models.family import Family, FamilyMember
from app.models.user import User

API_KEY_PREFIX = "pb_live_"

# auto_error=False so we can fall through to cookie auth or X-API-Key when header is absent.
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class WorkspaceContext:
    """Resolved household workspace for the current request.

    `owner_id` / `owner` is the household data owner whose bills, categories,
    bank accounts, imports, and stats are being accessed. `actor` is the
    authenticated user (either the owner or a family member). `scopes` is the
    effective permission set (family scopes intersected with API key scopes).
    """

    owner_id: int
    owner: User
    actor: User
    scopes: frozenset[str]
    is_owner: bool


def _authenticate_api_key(
    raw_key: str, db: Session
) -> tuple[User, frozenset[str]] | None:
    if not raw_key.startswith(API_KEY_PREFIX):
        return None
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_row = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None))
        .first()
    )
    if key_row is None:
        return None
    now = datetime.now(timezone.utc)
    if key_row.expires_at is not None and key_row.expires_at <= now:
        return None
    user = db.get(User, key_row.user_id)
    if not user or not user.is_active:
        return None
    if (
        key_row.last_used_at is None
        or (now - key_row.last_used_at).total_seconds() >= 60
    ):
        key_row.last_used_at = now
        db.commit()
    return user, frozenset(key_row.scopes or [])


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    # 1. Check X-API-Key header or Bearer pb_live_... API key.
    raw_api_key = request.headers.get("x-api-key")
    if (
        not raw_api_key
        and creds is not None
        and creds.credentials.startswith(API_KEY_PREFIX)
    ):
        raw_api_key = creds.credentials

    if raw_api_key is not None:
        auth_result = _authenticate_api_key(raw_api_key.strip(), db)
        if auth_result is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
            )
        user, key_scopes = auth_result
        request.state.is_api_key = True
        request.state.api_key_scopes = key_scopes
        return user

    # 2. Fall back to JWT Bearer or HttpOnly cookie.
    request.state.is_api_key = False
    request.state.api_key_scopes = None

    token: str | None = None
    if creds is not None:
        token = creds.credentials
    else:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    try:
        user_id = int(payload["sub"])
        token_version = int(payload.get("tv", 0))
    except (TypeError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    jwt_user = db.get(User, user_id)
    if not jwt_user or not jwt_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    if token_version != jwt_user.token_version:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Session revoked; please log in again"
        )
    return jwt_user


def require_session_auth(
    request: Request,
    user: User = Depends(current_user),
) -> User:
    """Reject API key authentication on sensitive account/security/admin endpoints."""
    if getattr(request.state, "is_api_key", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot access account, security, family, or system settings",
        )
    return user


def resolve_user_workspace(
    db: Session, actor: User
) -> tuple[int, User, frozenset[str], bool]:
    """Return (owner_id, owner, user_scopes, is_owner) for `actor`."""
    membership = db.query(FamilyMember).filter(FamilyMember.user_id == actor.id).first()
    if membership is not None:
        family = db.get(Family, membership.family_id)
        if family is not None:
            owner = db.get(User, family.owner_id)
            if owner is not None:
                return (
                    owner.id,
                    owner,
                    frozenset(membership.scopes or []),
                    owner.id == actor.id,
                )
    return actor.id, actor, ALL_SCOPES_SET, True


def workspace_context(required_scope: str | None = None):
    """Dependency factory enforcing household scoping and permission scopes."""

    def _dependency(
        request: Request,
        actor: User = Depends(current_user),
        db: Session = Depends(get_db),
    ) -> WorkspaceContext:
        owner_id, owner, user_scopes, is_owner = resolve_user_workspace(db, actor)
        api_scopes: frozenset[str] | None = getattr(
            request.state, "api_key_scopes", None
        )
        effective_scopes = (
            user_scopes & api_scopes if api_scopes is not None else user_scopes
        )
        if required_scope is not None and required_scope not in effective_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission scope: {required_scope}",
            )
        return WorkspaceContext(
            owner_id=owner_id,
            owner=owner,
            actor=actor,
            scopes=effective_scopes,
            is_owner=is_owner,
        )

    return _dependency


def optional_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Like current_user, but returns None instead of raising on any failure.

    Used for endpoints that must still work when the token has expired, been
    revoked, or fails the issuer/audience checks (e.g. logout, which clears
    the HttpOnly cookie a dead token has made otherwise unmatchable).
    """
    token: str | None = None
    if creds is not None:
        token = creds.credentials
    else:
        token = request.cookies.get("access_token")

    if not token:
        return None
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        return None
    try:
        user_id = int(payload["sub"])
        token_version = int(payload.get("tv", 0))
    except (TypeError, ValueError, KeyError):
        return None
    user = db.get(User, user_id)
    if not user or not user.is_active or token_version != user.token_version:
        return None
    return user


def require_install_owner(db: Session, me: User) -> None:
    """Fail-closed guard for process-wide settings (import, LLM, SMTP, Apprise, IMAP).

    Only the import target account (IMPORT_USER_EMAIL, or the sole user on a
    single-user install) may view or mutate install-global configuration.
    When multiple users exist without IMPORT_USER_EMAIL set, reject all callers
    rather than failing open.
    """
    from app.services.bill_import import resolve_import_user

    target = resolve_import_user(db)
    if target is None or target.id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the install owner can access or change global settings",
        )
