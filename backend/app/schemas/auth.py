import re
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import validate_password_strength
from app.core.timezones import validate_timezone

_CURRENCY_PATTERN = re.compile(r"^[A-Z0-9]{2,10}$")
_BCRYPT_MAX_PASSWORD_BYTES = 72


def _normalize_currency(value: str) -> str:
    normalized = value.strip().upper()
    if not _CURRENCY_PATTERN.match(normalized):
        raise ValueError("default_currency must be 2-10 alphanumeric characters")
    return normalized


def _reject_oversized_password(value: str) -> str:
    if len(value.encode("utf-8")) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must be at most {_BCRYPT_MAX_PASSWORD_BYTES} bytes "
            "when UTF-8 encoded"
        )
    return value


def _normalize_email(value: str) -> str:
    return value.lower()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        _reject_oversized_password(v)
        validate_password_strength(v)
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return _normalize_email(v)


class UserProfileOut(BaseModel):
    model_config = {"from_attributes": True}

    email: EmailStr
    language_preference: str | None
    timezone: str | None
    default_currency: str | None
    email_reminders_enabled: bool
    notify_2_days_before: bool
    notify_1_day_before: bool
    notify_on_day: bool
    notify_1_day_after: bool
    reminder_send_minute: int
    monthly_summary_enabled: bool
    upcoming_digest_enabled: bool
    upcoming_digest_weekday: int
    upcoming_digest_minute: int
    upcoming_digest_days: int


class UserProfileUpdate(BaseModel):
    language_preference: Literal["en", "pl", "de"] | None = None
    timezone: str | None = None
    default_currency: str | None = None
    email_reminders_enabled: bool | None = None
    notify_2_days_before: bool | None = None
    notify_1_day_before: bool | None = None
    notify_on_day: bool | None = None
    notify_1_day_after: bool | None = None
    reminder_send_minute: Annotated[int, Field(ge=0, le=1410)] | None = None
    monthly_summary_enabled: bool | None = None
    upcoming_digest_enabled: bool | None = None
    upcoming_digest_weekday: Annotated[int, Field(ge=0, le=6)] | None = None
    upcoming_digest_minute: Annotated[int, Field(ge=0, le=1410)] | None = None
    upcoming_digest_days: Annotated[int, Field(ge=1, le=30)] | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone_name(cls, v: str | None) -> str | None:
        return validate_timezone(v)

    @field_validator("default_currency")
    @classmethod
    def validate_default_currency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _normalize_currency(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        _reject_oversized_password(v)
        validate_password_strength(v)
        return v


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    current_password: str

    @field_validator("new_email")
    @classmethod
    def normalize_new_email(cls, v: str) -> str:
        return _normalize_email(v)


class SendNotificationNowOut(BaseModel):
    sent: int


class SendMonthlySummaryNowOut(BaseModel):
    sent: bool


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return _normalize_email(v)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _reject_oversized_password(v)


class SmtpStatusResponse(BaseModel):
    configured: bool


class NotificationStatusResponse(BaseModel):
    smtp_configured: bool
    apprise_configured: bool


class SendTestNotificationOut(BaseModel):
    ok: bool
    channel: str | None
    detail: str | None


class MessageResponse(BaseModel):
    message: str
