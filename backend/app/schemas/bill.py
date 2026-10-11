import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from app.models.bill import BillFrequency, PaymentStatus
from app.schemas.category import CategoryOut

_PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z0-9]{2,10}$")
_MAX_BACKUP_ENTRIES = 5000


def _validate_optional_period(value: str | None) -> str | None:
    if value is not None and not _PERIOD_PATTERN.match(value):
        raise ValueError("must be a YYYY-MM period")
    return value


def _validate_optional_iso_date(value: str | None) -> str | None:
    if value is not None:
        date.fromisoformat(value)
    return value


def _validate_optional_iso_datetime(value: str | None) -> str | None:
    if value is not None:
        datetime.fromisoformat(value)
    return value


class BillTemplateCreate(BaseModel):
    name: str = Field(max_length=255)
    category_id: int | None = None  # preferred
    category: str | None = None  # legacy default-key string, resolved server-side
    frequency: BillFrequency
    interval_count: int = Field(1, ge=1)
    max_occurrences: int | None = Field(None, ge=1, le=999)  # None = unlimited
    start_date: date | None = None  # weekly anchor ("first payment date")
    amount: Decimal = Decimal("0")
    amount_varies: bool = False  # usage-based bill: confirm each period
    currency: str = Field("PLN", pattern=_CURRENCY_PATTERN.pattern)
    due_day: int | None = Field(None, ge=1, le=31)
    due_month: int | None = Field(None, ge=1, le=12)  # month for annual/one_off
    notes: str | None = Field(None, max_length=5000)
    is_paused: bool = False

    @model_validator(mode="after")
    def require_a_category(self) -> "BillTemplateCreate":
        if self.category_id is None and self.category is None:
            raise ValueError("category_id or category is required")
        return self


class BillTemplateUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    category_id: int | None = None  # preferred
    category: str | None = None  # legacy default-key string, resolved server-side
    frequency: BillFrequency | None = None
    interval_count: int | None = Field(None, ge=1)
    max_occurrences: int | None = Field(None, ge=1, le=999)  # None = unlimited
    start_date: date | None = None
    amount: Decimal | None = None
    amount_varies: bool | None = None
    currency: str | None = Field(None, pattern=_CURRENCY_PATTERN.pattern)
    due_day: int | None = Field(None, ge=1, le=31)
    due_month: int | None = Field(None, ge=1, le=12)  # month for annual/one_off
    notes: str | None = Field(None, max_length=5000)
    is_paused: bool | None = None
    recreate_deleted_future: bool = False  # transient control flag — not persisted


class BillTemplateOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    category: CategoryOut
    frequency: BillFrequency
    interval_count: int = 1
    max_occurrences: int | None = None
    start_date: date | None = None
    amount: Decimal
    amount_varies: bool = False
    currency: str
    due_day: int | None
    notes: str | None
    is_archived: bool
    is_paused: bool
    created_at: datetime
    start_period: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def due_month(self) -> int | None:
        if self.start_period:
            return int(self.start_period.split("-")[1])
        return None


class PaymentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    instance_id: int
    amount: Decimal
    paid_on: date
    note: str | None
    created_at: datetime


class PaymentInstanceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    bill_id: int
    period: str
    due_date: date
    amount: Decimal
    amount_estimated: bool = False
    status: PaymentStatus
    paid_at: datetime | None
    paid_amount: Decimal | None
    notes: str | None
    bill_name: str
    currency: str
    frequency: BillFrequency
    interval_count: int = 1
    max_occurrences: int | None = None
    start_date: date | None = None
    category: CategoryOut
    email_sent_at: datetime | None
    payments: list[PaymentOut] = []


class PendingConfirmationOut(PaymentInstanceOut):
    """An unconfirmed variable-bill instance plus the amounts the
    suggestion was based on (newest first)."""

    basis_amounts: list[Decimal] = []


class InstanceAmountUpdate(BaseModel):
    amount: Decimal = Field(gt=0)


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    paid_on: date | None = None  # null means "today"
    note: str | None = None

    @field_validator("paid_on")
    @classmethod
    def reject_future_dates(cls, v: date | None) -> date | None:
        # One day of slack: a user ahead of UTC (up to +14) can legitimately
        # record a payment dated "tomorrow" in server-UTC terms.
        if v is not None and v > date.today() + timedelta(days=1):
            raise ValueError("paid_on cannot be in the future")
        return v


class MarkPaidRequest(BaseModel):
    paid_amount: Decimal | None = Field(
        None, gt=0
    )  # defaults to remaining balance when None
    notes: str | None = None


class HasDeletedFutureOut(BaseModel):
    has_deleted_future: bool


class GenerateInstancesRequest(BaseModel):
    months: int = Field(6, ge=1, le=24)
    bill_ids: list[int] | None = None


class GenerateInstancesOut(BaseModel):
    created: int
    bill_count: int
    months: int


_LEGACY_FREQUENCY_INTERVALS: dict[str, int] = {
    "every_2_months": 2,
    "quarterly": 3,
}


class BackupTemplate(BaseModel):
    id: int
    name: str
    category: str | None
    frequency: BillFrequency
    interval_count: int = Field(1, ge=1)
    max_occurrences: int | None = None
    start_date: str | None = None
    amount: Decimal
    amount_varies: bool = False
    currency: str
    due_day: int | None
    notes: str | None
    is_archived: bool
    is_paused: bool
    start_period: str | None
    created_at: str

    @field_validator("start_period")
    @classmethod
    def validate_start_period(cls, v: str | None) -> str | None:
        return _validate_optional_period(v)

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, v: str | None) -> str | None:
        return _validate_optional_iso_date(v)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, v: str) -> str:
        _validate_optional_iso_datetime(v)
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if not _CURRENCY_PATTERN.match(v):
            raise ValueError("currency must be 2-10 uppercase alphanumeric characters")
        return v

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_frequency(cls, data: object) -> object:
        """Map pre-v5 `every_2_months`/`quarterly` to monthly + interval.

        Only applies when the payload carries no explicit `interval_count`
        (v5 exports always do), so a v5 backup is never rewritten.
        """
        if not isinstance(data, dict):
            return data
        interval = _LEGACY_FREQUENCY_INTERVALS.get(str(data.get("frequency")))
        if interval is None or data.get("interval_count") is not None:
            return data
        return {**data, "frequency": "monthly", "interval_count": interval}


class BackupInstance(BaseModel):
    # Intentionally excluded from backup: reminder_sent_2_days_before,
    # reminder_sent_on_day, email_sent_at — transient flags reset to False on restore.
    id: int
    bill_id: int
    period: str
    due_date: str
    amount: Decimal
    amount_estimated: bool = False
    status: PaymentStatus
    paid_at: str | None
    paid_amount: Decimal | None
    notes: str | None
    created_at: str
    reminder_sent_upcoming: bool = False
    reminder_sent_overdue: bool = False

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        if not _PERIOD_PATTERN.match(v):
            raise ValueError("period must be a YYYY-MM period")
        return v

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, v: str) -> str:
        date.fromisoformat(v)
        return v

    @field_validator("paid_at", "created_at")
    @classmethod
    def validate_iso_datetimes(cls, v: str | None) -> str | None:
        return _validate_optional_iso_datetime(v)


class BackupPayment(BaseModel):
    id: int
    instance_id: int
    amount: Decimal
    paid_on: str
    note: str | None
    created_at: str

    @field_validator("paid_on")
    @classmethod
    def validate_paid_on(cls, v: str) -> str:
        date.fromisoformat(v)
        return v

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, v: str) -> str:
        _validate_optional_iso_datetime(v)
        return v


class BackupPayload(BaseModel):
    schema_version: int
    bill_templates: list[BackupTemplate] = Field(max_length=_MAX_BACKUP_ENTRIES)
    payment_instances: list[BackupInstance] = Field(max_length=_MAX_BACKUP_ENTRIES)
    payments: list[BackupPayment] = Field(default=[], max_length=_MAX_BACKUP_ENTRIES)


class ExportSummaryOut(BaseModel):
    bill_count: int
    payment_count: int


class RestoreSnapshotOut(BaseModel):
    created_at: datetime
