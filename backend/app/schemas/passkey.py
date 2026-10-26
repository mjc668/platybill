from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PasskeyOut(BaseModel):
    id: int
    name: str
    credential_id: str
    created_at: datetime
    last_used_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PasskeyRegistrationOptionsResponse(BaseModel):
    options: dict[str, Any]


class PasskeyRegistrationVerifyRequest(BaseModel):
    response: dict[str, Any]
    name: str | None = None


class PasskeyLoginOptionsResponse(BaseModel):
    options: dict[str, Any]


class PasskeyLoginVerifyRequest(BaseModel):
    response: dict[str, Any]
    remember_me: bool = True
