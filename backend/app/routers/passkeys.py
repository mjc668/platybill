from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import current_user
from app.core.ratelimit import rate_limited
from app.core.security import create_access_token
from app.models.passkey import Passkey
from app.models.user import User
from app.routers.auth import _set_auth_cookie
from app.schemas.auth import MessageResponse
from app.schemas.passkey import (
    PasskeyLoginOptionsResponse,
    PasskeyLoginVerifyRequest,
    PasskeyOut,
    PasskeyRegistrationOptionsResponse,
    PasskeyRegistrationVerifyRequest,
)
from app.services.passkeys import (
    generate_login_options,
    generate_registration_options_for_user,
    verify_login_credential,
    verify_registration_credential,
)

router = APIRouter(prefix="/auth/passkeys", tags=["passkeys"])


@router.post(
    "/register/options",
    response_model=PasskeyRegistrationOptionsResponse,
)
def get_registration_options(
    request: Request,
    user: User = Depends(current_user),
) -> PasskeyRegistrationOptionsResponse:
    options = generate_registration_options_for_user(user, request)
    return PasskeyRegistrationOptionsResponse(options=options)


@router.post(
    "/register/verify",
    response_model=PasskeyOut,
    status_code=status.HTTP_201_CREATED,
)
def verify_registration(
    request: Request,
    body: PasskeyRegistrationVerifyRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PasskeyOut:
    (
        credential_id,
        public_key,
        sign_count,
        aaguid,
        transports,
    ) = verify_registration_credential(user, body.response, request)

    existing = db.query(Passkey).filter(Passkey.credential_id == credential_id).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This passkey is already registered",
        )

    passkey_name = (body.name or "").strip() or "Device Passkey"
    passkey = Passkey(
        user_id=user.id,
        credential_id=credential_id,
        public_key=public_key,
        sign_count=sign_count,
        name=passkey_name,
        aaguid=aaguid,
        transports=transports,
    )
    db.add(passkey)
    db.commit()
    db.refresh(passkey)
    return PasskeyOut.model_validate(passkey)


@router.post(
    "/login/options",
    response_model=PasskeyLoginOptionsResponse,
)
def get_login_options(
    request: Request,
    _rl: None = Depends(rate_limited("passkey")),
) -> PasskeyLoginOptionsResponse:
    options = generate_login_options(request)
    return PasskeyLoginOptionsResponse(options=options)


@router.post(
    "/login/verify",
    response_model=MessageResponse,
)
def verify_login(
    request: Request,
    body: PasskeyLoginVerifyRequest,
    response: Response,
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limited("passkey")),
) -> MessageResponse:
    credential_id = body.response.get("id")
    if not credential_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing credential id in passkey response",
        )

    passkey = db.query(Passkey).filter(Passkey.credential_id == credential_id).first()
    if passkey is None or not passkey.user or not passkey.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Passkey not recognized or account disabled",
        )

    new_sign_count = verify_login_credential(body.response, passkey, request)

    passkey.sign_count = new_sign_count
    passkey.last_used_at = datetime.now(timezone.utc)
    db.commit()

    if body.remember_me:
        expires_delta = timedelta(days=settings.remember_me_expire_days)
        max_age = settings.remember_me_expire_days * 86400
    else:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        max_age = settings.access_token_expire_minutes * 60

    token = create_access_token(
        str(passkey.user.id),
        token_version=passkey.user.token_version,
        expires_delta=expires_delta,
    )
    _set_auth_cookie(response, token, max_age=max_age)

    return MessageResponse(message="Signed in successfully with Passkey.")


@router.get(
    "",
    response_model=list[PasskeyOut],
)
def list_passkeys(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[PasskeyOut]:
    passkeys = (
        db.query(Passkey)
        .filter(Passkey.user_id == user.id)
        .order_by(Passkey.created_at.desc())
        .all()
    )
    return [PasskeyOut.model_validate(p) for p in passkeys]


@router.delete(
    "/{passkey_id}",
    response_model=MessageResponse,
)
def delete_passkey(
    passkey_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    passkey = (
        db.query(Passkey)
        .filter(Passkey.id == passkey_id, Passkey.user_id == user.id)
        .first()
    )
    if passkey is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passkey not found",
        )

    db.delete(passkey)
    db.commit()
    return MessageResponse(message="Passkey removed successfully.")
