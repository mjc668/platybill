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


class ImportSettingsIn(BaseModel):
    enabled: bool | None = None
    directory: str | None = Field(None, max_length=255)
    poll_minutes: int | None = Field(None, ge=1, le=1440)
    ollama_base_url: str | None = Field(None, max_length=255)
    ollama_model: str | None = Field(None, max_length=255)
    llm_provider: str | None = Field(None, max_length=20)
    llm_model: str | None = Field(None, max_length=255)
    llm_base_url: str | None = Field(None, max_length=255)
    llm_api_key: str | None = Field(None, max_length=500)
    llm_timeout_seconds: float | None = Field(None, ge=1, le=600)
    imap_host: str | None = Field(None, max_length=255)
    imap_port: int | None = Field(None, ge=1, le=65535)
    imap_user: str | None = Field(None, max_length=255)
    imap_password: str | None = Field(None, max_length=500)
    imap_folder: str | None = Field(None, max_length=255)
    imap_tls: bool | None = None
    imap_poll_minutes: int | None = Field(None, ge=1, le=1440)
    imap_mark_read: bool | None = None
    imap_allowed_senders: str | None = Field(None, max_length=2000)


class ImportStatusOut(BaseModel):
    ollama_configured: bool
    ollama_base_url: str | None
    ollama_reachable: bool
    ollama_model: str
    model_available: bool | None
    available_models: list[str] = []
    llm_provider: str
    llm_model: str
    llm_base_url: str | None
    llm_configured: bool
    llm_api_key_configured: bool
    import_enabled: bool
    import_dir: str
    import_poll_minutes: int
    imap_configured: bool
    imap_user: str | None
    imap_host: str | None
    imap_port: int
    imap_folder: str
    imap_tls: bool
    imap_poll_minutes: int
    imap_mark_read: bool
    imap_password_configured: bool
    pending_count: int
    last_error: str | None


class TestOllamaOut(BaseModel):
    ok: bool
    model: str
    model_available: bool
    error: str | None = None


class TestImapOut(BaseModel):
    ok: bool
    folder: str | None = None
    unseen: int | None = None
    error: str | None = None


class ScanNowOut(BaseModel):
    directory: dict
    email: dict
