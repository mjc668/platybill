from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import API_KEY_PREFIX, require_session_auth, resolve_user_workspace
from app.core.ratelimit import rate_limited_by_user
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_key import ApiKeyCreatedOut, ApiKeyCreateRequest, ApiKeyOut

router = APIRouter(prefix="/auth/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(
    me: User = Depends(require_session_auth),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == me.id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return rows


@router.post("", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreateRequest,
    me: User = Depends(require_session_auth),
    _rl: None = Depends(rate_limited_by_user("api_key")),
    db: Session = Depends(get_db),
):
    _, _, user_scopes, _ = resolve_user_workspace(db, me)
    requested = set(body.scopes)
    if not requested.issubset(user_scopes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create an API key with scopes you do not hold",
        )

    raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_prefix = raw_key[:16]
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None
        else None
    )

    row = ApiKey(
        user_id=me.id,
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ApiKeyCreatedOut(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        scopes=list(row.scopes or []),
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        key=raw_key,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    key_id: int,
    me: User = Depends(require_session_auth),
    db: Session = Depends(get_db),
):
    row = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == me.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(row)
    db.commit()
