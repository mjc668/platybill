from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import webauthn
from fastapi import HTTPException, Request, status
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import settings
from app.models.passkey import Passkey
from app.models.user import User

logger = logging.getLogger(__name__)


@dataclass
class _ChallengeEntry:
    challenge: bytes
    user_id: int | None
    expires_at: float


class ChallengeCache:
    """In-memory cache for WebAuthn challenges with automatic TTL expiry."""

    def __init__(self, default_ttl: int = 300) -> None:
        self._default_ttl = default_ttl
        self._cache: dict[str, _ChallengeEntry] = {}

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._cache.items() if v.expires_at < now]
        for k in expired:
            self._cache.pop(k, None)

    def save(self, challenge: bytes, user_id: int | None = None) -> str:
        self._purge_expired()
        key = bytes_to_base64url(challenge)
        self._cache[key] = _ChallengeEntry(
            challenge=challenge,
            user_id=user_id,
            expires_at=time.time() + self._default_ttl,
        )
        return key

    def pop(self, challenge_key: str) -> _ChallengeEntry | None:
        self._purge_expired()
        entry = self._cache.pop(challenge_key, None)
        if entry is None or entry.expires_at < time.time():
            return None
        return entry


challenge_cache = ChallengeCache()


def resolve_rp_id(request: Request) -> str:
    """Determine the Relying Party ID (effective domain)."""
    if settings.webauthn_rp_id:
        return settings.webauthn_rp_id

    # If origin header is present, use its hostname
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.hostname:
            return parsed.hostname

    # Otherwise fall back to host header
    host = request.headers.get("host", "").split(":")[0]
    if host:
        return host
    return request.url.hostname or "localhost"


def resolve_expected_origins(request: Request) -> list[str]:
    """Compile accepted origins for WebAuthn response verification."""
    origins: list[str] = []

    # Client-sent Origin header is the most specific
    client_origin = request.headers.get("origin")
    if client_origin:
        origins.append(client_origin.rstrip("/"))

    scheme = request.url.scheme
    if settings.cookie_secure:
        scheme = "https"
    if settings.trust_proxy and request.headers.get("x-forwarded-proto"):
        scheme = request.headers.get("x-forwarded-proto", scheme)

    host = request.headers.get("host")
    if host:
        origins.append(f"{scheme}://{host}".rstrip("/"))

    base = str(request.base_url).rstrip("/")
    if base and base not in origins:
        origins.append(base)

    for o in settings.allowed_origins:
        cleaned = o.rstrip("/")
        if cleaned not in origins:
            origins.append(cleaned)

    return origins


def generate_registration_options_for_user(
    user: User, request: Request
) -> dict[str, Any]:
    rp_id = resolve_rp_id(request)
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id))
        for p in user.passkeys
    ]

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.email,
        user_display_name=user.email,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials if exclude_credentials else None,
    )

    challenge_cache.save(options.challenge, user_id=user.id)
    return json.loads(webauthn.options_to_json(options))


def verify_registration_credential(
    user: User,
    credential_data: dict[str, Any],
    request: Request,
) -> tuple[str, bytes, int, str | None, str | None]:
    """Verify registration credential and return fields for Passkey row."""
    try:
        credential = parse_registration_credential_json(credential_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid registration credential format: {exc}",
        ) from exc

    challenge_key = bytes_to_base64url(credential.response.client_data.challenge)
    entry = challenge_cache.pop(challenge_key)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration challenge is invalid or has expired",
        )

    rp_id = resolve_rp_id(request)
    expected_origins = resolve_expected_origins(request)

    try:
        verified = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=entry.challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origins,
            require_user_verification=False,
        )
    except Exception as exc:
        logger.warning("Passkey registration failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Passkey verification failed: {exc}",
        ) from exc

    credential_id_str = bytes_to_base64url(verified.credential_id)
    transports_str = (
        ",".join(credential.response.transports)
        if hasattr(credential.response, "transports") and credential.response.transports
        else None
    )

    return (
        credential_id_str,
        verified.credential_public_key,
        verified.sign_count,
        verified.aaguid,
        transports_str,
    )


def generate_login_options(request: Request) -> dict[str, Any]:
    rp_id = resolve_rp_id(request)
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    challenge_cache.save(options.challenge)
    return json.loads(webauthn.options_to_json(options))


def verify_login_credential(
    credential_data: dict[str, Any],
    passkey: Passkey,
    request: Request,
) -> int:
    """Verify authentication credential and return updated sign_count."""
    try:
        credential = parse_authentication_credential_json(credential_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid authentication credential format: {exc}",
        ) from exc

    challenge_key = bytes_to_base64url(credential.response.client_data.challenge)
    entry = challenge_cache.pop(challenge_key)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication challenge is invalid or has expired",
        )

    rp_id = resolve_rp_id(request)
    expected_origins = resolve_expected_origins(request)

    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=entry.challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origins,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=False,
        )
    except Exception as exc:
        logger.warning("Passkey authentication failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Passkey authentication failed: {exc}",
        ) from exc

    return verified.new_sign_count
