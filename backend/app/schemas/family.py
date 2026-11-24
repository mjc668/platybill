from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.scopes import validate_scopes
from app.core.security import validate_password_strength


def _reject_oversized_password(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes when UTF-8 encoded")
    validate_password_strength(value)
    return value


class FamilyMemberOut(BaseModel):
    id: int
    user_id: int
    email: EmailStr
    scopes: list[str]
    created_at: datetime


class FamilyInviteOut(BaseModel):
    id: int
    family_id: int
    family_name: str
    owner_email: EmailStr
    email: EmailStr
    scopes: list[str]
    expires_at: datetime
    created_at: datetime


class FamilyOverviewOut(BaseModel):
    is_owner: bool
    family_id: int | None
    family_name: str | None
    owner_email: EmailStr | None
    my_scopes: list[str]
    members: list[FamilyMemberOut]
    outgoing_invites: list[FamilyInviteOut]
    incoming_invites: list[FamilyInviteOut]


class FamilyMemberAddRequest(BaseModel):
    email: EmailStr
    scopes: list[str]
    initial_password: Annotated[str | None, Field(min_length=8)] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("scopes")
    @classmethod
    def check_scopes(cls, v: list[str]) -> list[str]:
        return validate_scopes(v)

    @field_validator("initial_password")
    @classmethod
    def check_password(cls, v: str | None) -> str | None:
        return _reject_oversized_password(v)


class FamilyMemberUpdateRequest(BaseModel):
    scopes: list[str]

    @field_validator("scopes")
    @classmethod
    def check_scopes(cls, v: list[str]) -> list[str]:
        return validate_scopes(v)
