from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.core.scopes import validate_scopes


class ApiKeyCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    scopes: list[str]
    expires_in_days: Annotated[int | None, Field(ge=1, le=3650)] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("API key name must not be empty")
        return cleaned

    @field_validator("scopes")
    @classmethod
    def check_scopes(cls, v: list[str]) -> list[str]:
        return validate_scopes(v)


class ApiKeyOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    key: str
