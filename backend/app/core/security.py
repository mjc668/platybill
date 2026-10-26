import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

_JWT_ISSUER = "platybill-backend"
_JWT_AUDIENCE = "platybill"

_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty",
        "qwerty123",
        "abc12345",
        "abcdefgh",
        "iloveyou",
        "welcome",
        "letmein",
        "monkey",
        "dragon",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "superman",
        "trustno1",
        "whatever",
        "changeme",
        "default",
        "11111111",
        "111111111",
        "00000000",
        "zaq12wsx",
        "passw0rd",
        "admin123",
        "letmein1",
        "qwerty1234",
        "asdfghjk",
        "zxcvbnm",
        "master123",
    }
)


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds bcrypt's 72-byte input limit."""


def hash_password(password: str) -> str:
    try:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    except ValueError as exc:
        raise PasswordTooLongError("Password exceeds bcrypt's 72-byte limit") from exc


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # Malformed hash or an over-long password: never a valid credential.
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common; pick something less predictable")


def create_access_token(
    subject: str,
    *,
    token_version: int = 0,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "tv": token_version,
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        audience=_JWT_AUDIENCE,
        issuer=_JWT_ISSUER,
    )
    return payload
