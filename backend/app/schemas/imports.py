from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.import_draft import ImportSource, ImportStatus


class ImportDraftOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    source: ImportSource
    filename: str | None
    provider: str | None
    amount: Decimal | None
    currency: str | None
    due_date: date | None
    period: str | None
    matched_bill_id: int | None
    matched_bill_name: str | None = None
    status: ImportStatus
    error: str | None
    created_at: datetime
    processed_at: datetime | None


class ImportDraftUpdate(BaseModel):
    provider: str | None = Field(None, max_length=255)
    amount: Decimal | None = Field(None, gt=0)
    currency: str | None = Field(None, max_length=10)
    due_date: date | None = None
    period: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    matched_bill_id: int | None = None


class ImportConfirmIn(BaseModel):
    bill_id: int | None = None


class ImportConfirmOut(BaseModel):
    draft_id: int
    bill_id: int
    instance_id: int
    created_instance: bool


class ImportStatusOut(BaseModel):
    ollama_configured: bool
    ollama_reachable: bool
    ollama_model: str
    model_available: bool | None
    import_enabled: bool
    import_dir: str
    imap_configured: bool
    imap_user: str | None
    pending_count: int
    last_error: str | None


class TestOllamaOut(BaseModel):
    ok: bool
    model: str
    model_available: bool
    error: str | None = None


class ScanNowOut(BaseModel):
    directory: dict
    email: dict
