from pydantic import BaseModel, Field, field_validator

_MAX_NAME_LENGTH = 100
_MAX_IBAN_LENGTH = 34
_MAX_NOTE_LENGTH = 255


def _clean_optional(value: str | None, *, what: str, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise ValueError(f"{what} must be at most {limit} characters")
    return cleaned


class BankAccountOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    iban: str | None
    note: str | None
    is_archived: bool


class BankAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=_MAX_NAME_LENGTH)
    iban: str | None = Field(None, max_length=_MAX_IBAN_LENGTH)
    note: str | None = Field(None, max_length=_MAX_NOTE_LENGTH)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("iban", "note")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class BankAccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=_MAX_NAME_LENGTH)
    iban: str | None = Field(None, max_length=_MAX_IBAN_LENGTH)
    note: str | None = Field(None, max_length=_MAX_NOTE_LENGTH)
    is_archived: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("iban", "note")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None
