"""Bill import pipeline: drafts, matching, apply, directory and IMAP pollers.

Every import becomes an ImportDraft; nothing is written to bills or instances
until the user confirms. `source_ref` dedupes (file hash or IMAP message-id +
part index), so re-polls never duplicate drafts.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.timezones import user_today
from app.models.bill import BillFrequency, BillTemplate, PaymentInstance, PaymentStatus
from app.models.import_draft import ImportDraft, ImportSource, ImportStatus
from app.models.user import User
from app.services import app_settings
from app.services.bank_accounts import get_for_user as get_account_for_user
from app.services.afterpay_parser import (
    BnplInstallmentRow,
    is_afterpay_email,
    merchants_match,
    parse_afterpay,
)
from app.services.bill_extract import (
    ExtractedBill,
    extract_bnpl_from_text,
    extract_document,
    extract_document_items,
    extract_from_text,
)
from app.services.llm import LlmUnavailable
from app.services.payments import recalculate_instance
from app.services.recurrence import _due_date_for_period

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg"}
_CONTENT_TYPE_ALIASES: dict[str, str] = {
    "application/x-pdf": "application/pdf",
    "application/acrobat": "application/pdf",
    "application/vnd.pdf": "application/pdf",
    "text/pdf": "application/pdf",
    "image/jpg": "image/jpeg",
}
_SUFFIX_TO_CONTENT_TYPE: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_ACTIVE_DRAFT_STATUSES = (ImportStatus.pending, ImportStatus.confirmed)
MATCH_THRESHOLD = 0.5
_IMAP_TIMEOUT_SECONDS = 30.0


def _detect_document_content_type(
    content_type: str | None, filename: str | None, payload: bytes
) -> str | None:
    """Resolve a supported document MIME type via header, alias, magic, or suffix."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized in ALLOWED_CONTENT_TYPES:
        return normalized
    if normalized in _CONTENT_TYPE_ALIASES:
        return _CONTENT_TYPE_ALIASES[normalized]

    # Magic bytes fallback (handles application/octet-stream and untyped parts).
    if payload.lstrip()[:5] == b"%PDF-":
        return "application/pdf"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    # Filename suffix fallback.
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _SUFFIX_TO_CONTENT_TYPE:
            return _SUFFIX_TO_CONTENT_TYPE[suffix]
    return None


class _HtmlTextExtractor(HTMLParser):
    """Strip HTML tags, skipping script/style blocks, preserving readable breaks."""

    _SKIP_TAGS = {"script", "style", "head"}
    _BLOCK_TAGS = {
        "p",
        "div",
        "br",
        "tr",
        "li",
        "td",
        "th",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "header",
        "footer",
    }

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in self._SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and lower in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and lower in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def _html_to_text(raw_html: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(raw_html)
    parser.close()
    return parser.get_text()


def _has_active_draft(db: Session, source_ref: str) -> bool:
    """True when an active (pending/confirmed) draft already exists for source_ref."""
    return (
        db.query(ImportDraft.id)
        .filter(
            ImportDraft.source_ref == source_ref,
            ImportDraft.status.in_(_ACTIVE_DRAFT_STATUSES),
        )
        .first()
        is not None
    )


def record_failed_draft(
    db: Session,
    *,
    user_id: int,
    source: ImportSource,
    source_ref: str,
    filename: str | None,
    error: str,
) -> ImportDraft:
    """Persist a visible failed import record (does not block later re-imports)."""
    draft = ImportDraft(
        user_id=user_id,
        source=source,
        source_ref=source_ref,
        filename=filename,
        status=ImportStatus.failed,
        error=error[:2000],
        processed_at=_now(),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SERVICE_KEYWORD_GROUPS: dict[str, str] = {
    "water": "water",
    "sewer": "water",
    "sewerage": "water",
    "rates": "rates",
    "waste": "waste",
    "rubbish": "waste",
    "garbage": "waste",
    "electricity": "electricity",
    "power": "electricity",
    "gas": "gas",
    "internet": "internet",
    "nbn": "internet",
    "broadband": "internet",
    "mobile": "phone",
    "phone": "phone",
    "insurance": "insurance",
    "strata": "strata",
    "levy": "strata",
    "levies": "strata",
    "rent": "rent",
}


def _tokens(value: str) -> set[str]:
    return {
        t
        for t in "".join(c.lower() if c.isalnum() else " " for c in value).split()
        if len(t) > 2
    }


def _service_groups(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        _SERVICE_KEYWORD_GROUPS[t]
        for t in _tokens(value)
        if t in _SERVICE_KEYWORD_GROUPS
    }


def _due_day_matches(bill: BillTemplate, due_date: date | None) -> bool:
    if due_date is None or bill.due_day is None:
        return False
    expected = _due_date_for_period(due_date.strftime("%Y-%m"), bill.due_day)
    return expected == due_date


def resolve_import_user(db: Session) -> User | None:
    """Account that polled imports belong to.

    `IMPORT_USER_EMAIL` wins; otherwise the app must have exactly one user.
    """
    if settings.import_user_email:
        return (
            db.query(User)
            .filter(User.email == settings.import_user_email.lower())
            .first()
        )
    users = db.query(User).order_by(User.id).limit(2).all()
    return users[0] if len(users) == 1 else None


def _afterpay_merchant_tokens(value: str) -> tuple[list[str], bool]:
    stripped = value.strip()
    if stripped.lower().startswith("afterpay:"):
        stripped = stripped[len("afterpay:") :].strip()
    truncated = stripped.endswith("...") or stripped.endswith("…")
    cleaned = stripped.rstrip(".… ")
    raw_tokens = "".join(c.lower() if c.isalnum() else " " for c in cleaned).split()
    tokens: list[str] = []
    for idx, tok in enumerate(raw_tokens):
        is_last_truncated = truncated and idx == len(raw_tokens) - 1
        if len(tok) > 2 or (is_last_truncated and len(tok) >= 2):
            tokens.append(tok)
    return tokens, truncated


def _score_afterpay_match(provider: str, bill_name: str) -> float:
    if "afterpay" not in bill_name.lower():
        return 0.0
    if merchants_match(provider, bill_name):
        return 1.0
    p_tokens, p_truncated = _afterpay_merchant_tokens(provider)
    b_tokens, _ = _afterpay_merchant_tokens(bill_name)
    if not p_tokens or not b_tokens:
        return 0.0
    b_set = set(b_tokens)
    matched = 0
    for idx, tok in enumerate(p_tokens):
        if tok in b_set:
            matched += 1
        elif (
            p_truncated
            and idx == len(p_tokens) - 1
            and any(bt.startswith(tok) for bt in b_tokens)
        ):
            matched += 1
    return matched / len(p_tokens) if matched else 0.0


def match_bill(
    db: Session,
    user_id: int,
    extracted: ExtractedBill,
    *,
    filename: str | None = None,
) -> int | None:
    """Match an extracted document to an active bill template.

    Afterpay drafts ("Afterpay: <merchant>") use dedicated merchant matching
    against active Afterpay templates first. For all other bills, issuer token
    overlap (against template name and notes) is the first pass; candidates
    whose service keyword explicitly contradicts the document are disqualified;
    tied templates are disambiguated by service keywords and due day; and
    remaining ambiguity returns None so the draft stays pending.
    """
    if not extracted.provider:
        return None
    bills = (
        db.query(BillTemplate)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_archived.is_(False),
            BillTemplate.is_deleted.is_(False),
        )
        .all()
    )
    if extracted.provider.strip().lower().startswith("afterpay:"):
        best_id: int | None = None
        best_score = 0.0
        for bill in bills:
            score = _score_afterpay_match(extracted.provider, bill.name)
            if score > best_score:
                best_id, best_score = bill.id, score
        return best_id if best_score >= MATCH_THRESHOLD else None

    provider_tokens = _tokens(extracted.provider)
    if not provider_tokens:
        return None

    doc_text = " ".join(
        part for part in (extracted.provider, extracted.raw_text, filename) if part
    )
    doc_services = _service_groups(doc_text)

    candidates: list[tuple[BillTemplate, float]] = []
    for bill in bills:
        bill_tokens = _tokens(bill.name) | (
            _tokens(bill.notes) if bill.notes else set()
        )
        overlap = provider_tokens & bill_tokens
        if not overlap:
            continue
        score = len(overlap) / len(provider_tokens)
        if score < MATCH_THRESHOLD:
            continue
        bill_services = _service_groups(bill.name)
        if bill_services and doc_services and bill_services.isdisjoint(doc_services):
            continue
        candidates.append((bill, score))

    if not candidates:
        return None

    best_score = max(score for _, score in candidates)
    top = [bill for bill, score in candidates if score == best_score]
    if len(top) == 1:
        return top[0].id

    def _disambig_score(bill: BillTemplate) -> int:
        service_hit = 1 if (_service_groups(bill.name) & doc_services) else 0
        due_hit = 1 if _due_day_matches(bill, extracted.due_date) else 0
        return service_hit + due_hit

    scored = [(bill, _disambig_score(bill)) for bill in top]
    best_disambig = max(score for _, score in scored)
    if best_disambig == 0:
        return None
    winners = [bill for bill, score in scored if score == best_disambig]
    return winners[0].id if len(winners) == 1 else None


def _is_duplicate_bnpl_instalment(
    db: Session,
    user_id: int,
    row: BnplInstallmentRow,
    matched_bill_id: int | None,
) -> bool:
    """True when (merchant, amount, due_date) already exists as a draft or payment instance."""
    provider_name = f"Afterpay: {row.merchant}"

    # 1. Existing pending/confirmed drafts with the same due_date and amount.
    existing_drafts = (
        db.query(ImportDraft)
        .filter(
            ImportDraft.user_id == user_id,
            ImportDraft.due_date == row.due_date,
            ImportDraft.amount == row.amount,
            ImportDraft.status.in_([ImportStatus.pending, ImportStatus.confirmed]),
        )
        .all()
    )
    for draft in existing_drafts:
        if matched_bill_id is not None and draft.matched_bill_id == matched_bill_id:
            return True
        if draft.provider and merchants_match(provider_name, draft.provider):
            return True

    # 2. Existing non-deleted payment instances with the same due_date and amount.
    existing_instances = (
        db.query(PaymentInstance, BillTemplate)
        .outerjoin(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            or_(
                and_(
                    PaymentInstance.bill_id.is_not(None),
                    BillTemplate.user_id == user_id,
                    BillTemplate.is_deleted.is_(False),
                ),
                and_(
                    PaymentInstance.bill_id.is_(None),
                    PaymentInstance.user_id == user_id,
                ),
            ),
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.due_date == row.due_date,
            PaymentInstance.amount == row.amount,
        )
        .all()
    )
    for inst, bill in existing_instances:
        if matched_bill_id is not None and inst.bill_id == matched_bill_id:
            return True
        name = inst.label if inst.label else (bill.name if bill is not None else "")
        if "afterpay" in name.lower() and merchants_match(provider_name, name):
            return True

    return False


@dataclass
class ImportDocumentResult:
    """Result of importing one uploaded or folder-polled document."""

    drafts: list[ImportDraft]
    skipped_duplicates: int = 0
    already_imported_file: bool = False


def create_draft(
    db: Session,
    *,
    user_id: int,
    source: ImportSource,
    source_ref: str,
    filename: str | None,
    extracted: ExtractedBill,
    meta: dict | None = None,
) -> ImportDraft | None:
    """Insert a draft unless an active (pending/confirmed) draft already exists."""
    if _has_active_draft(db, source_ref):
        return None
    draft_meta: dict[str, Any] | None = dict(meta) if meta is not None else None
    if extracted.warnings:
        draft_meta = dict(draft_meta) if draft_meta is not None else {}
        existing_warnings = list(draft_meta.get("warnings") or [])
        for warning in extracted.warnings:
            if warning not in existing_warnings:
                existing_warnings.append(warning)
        draft_meta["warnings"] = existing_warnings
    draft = ImportDraft(
        user_id=user_id,
        source=source,
        source_ref=source_ref,
        filename=filename,
        provider=extracted.provider,
        amount=extracted.amount,
        currency=extracted.currency,
        due_date=extracted.due_date,
        period=extracted.period,
        raw_text=extracted.raw_text,
        matched_bill_id=match_bill(db, user_id, extracted, filename=filename),
        status=ImportStatus.pending,
        meta=draft_meta,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _max_bytes() -> int:
    return settings.import_max_file_mb * 1024 * 1024


def import_document_drafts(
    db: Session,
    *,
    user_id: int,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    source: ImportSource,
) -> ImportDocumentResult:
    """Extract a document and store one (single bill) or N (BNPL list) pending drafts."""
    if len(data) > _max_bytes():
        raise ValueError(
            f"File exceeds IMPORT_MAX_FILE_MB ({settings.import_max_file_mb})"
        )
    file_hash = _hash(data)
    base_ref = f"{source.value}:{file_hash}"
    bnpl_prefix = f"{base_ref}:afterpay:"

    # Reject exact file re-uploads across all draft statuses before calling the LLM.
    if (
        db.query(ImportDraft)
        .filter(
            or_(
                ImportDraft.source_ref == base_ref,
                ImportDraft.source_ref.like(f"{bnpl_prefix}%"),
            )
        )
        .first()
        is not None
    ):
        return ImportDocumentResult(
            drafts=[], skipped_duplicates=1, already_imported_file=True
        )

    config = app_settings.llm_config(db)
    if config is None:
        raise LlmUnavailable("No LLM provider is configured (set one up in Settings)")

    user = db.get(User, user_id)
    ref_date = user_today(user.timezone if user else None)
    doc = extract_document_items(
        data,
        config=config,
        content_type=content_type,
        filename=filename,
        reference_date=ref_date,
    )

    if doc.bnpl_installments:
        created: list[ImportDraft] = []
        skipped = 0
        for row_index, row in enumerate(doc.bnpl_installments):
            extracted = ExtractedBill(
                provider=f"Afterpay: {row.merchant}",
                amount=row.amount,
                currency=row.currency,
                due_date=row.due_date,
                period=row.due_date.strftime("%Y-%m"),
                confidence=1.0,
                raw_text=doc.raw_text,
            )
            matched_bill_id = match_bill(db, user_id, extracted)
            if _is_duplicate_bnpl_instalment(db, user_id, row, matched_bill_id):
                skipped += 1
                continue
            row_ref = f"{bnpl_prefix}{row_index}"
            draft = create_draft(
                db,
                user_id=user_id,
                source=source,
                source_ref=row_ref,
                filename=filename,
                extracted=extracted,
                meta=row.to_meta(),
            )
            if draft is None:
                skipped += 1
            else:
                created.append(draft)
        return ImportDocumentResult(drafts=created, skipped_duplicates=skipped)

    if doc.bill is None:
        return ImportDocumentResult(drafts=[], skipped_duplicates=0)

    draft = create_draft(
        db,
        user_id=user_id,
        source=source,
        source_ref=base_ref,
        filename=filename,
        extracted=doc.bill,
    )
    if draft is None:
        return ImportDocumentResult(
            drafts=[], skipped_duplicates=1, already_imported_file=True
        )
    return ImportDocumentResult(drafts=[draft], skipped_duplicates=0)


def import_document(
    db: Session,
    *,
    user_id: int,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    source: ImportSource,
) -> ImportDraft | None:
    """Extract a document and store it as a draft; None when it is a duplicate."""
    result = import_document_drafts(
        db,
        user_id=user_id,
        data=data,
        filename=filename,
        content_type=content_type,
        source=source,
    )
    return result.drafts[0] if result.drafts else None


def import_text(
    db: Session,
    *,
    user_id: int,
    text: str,
    source_ref: str,
    filename: str | None,
    source: ImportSource,
) -> ImportDraft | None:
    if _has_active_draft(db, source_ref):
        return None
    config = app_settings.llm_config(db)
    if config is None:
        raise LlmUnavailable("No LLM provider is configured (set one up in Settings)")
    user = db.get(User, user_id)
    ref_date = user_today(user.timezone if user else None)
    extracted = extract_from_text(text, config=config, reference_date=ref_date)
    return create_draft(
        db,
        user_id=user_id,
        source=source,
        source_ref=source_ref,
        filename=filename,
        extracted=extracted,
    )


def _target_instance(
    db: Session,
    bill: BillTemplate,
    period: str,
    *,
    due_date: date | None = None,
    fallback_to_estimate: bool = False,
) -> PaymentInstance | None:
    if due_date is not None:
        # Prefer an exact due_date match (including paid instances so callers
        # reject an already-paid instalment instead of falling back to another
        # unpaid instalment in the same month).
        by_due_date = (
            db.query(PaymentInstance)
            .filter(
                PaymentInstance.bill_id == bill.id,
                PaymentInstance.is_deleted.is_(False),
                PaymentInstance.due_date == due_date,
            )
            .first()
        )
        if by_due_date is not None:
            return by_due_date
    query = db.query(PaymentInstance).filter(
        PaymentInstance.bill_id == bill.id,
        PaymentInstance.is_deleted.is_(False),
        PaymentInstance.status != PaymentStatus.paid,
    )
    by_period = (
        query.filter(PaymentInstance.period == period)
        .order_by(PaymentInstance.due_date)
        .first()
    )
    if by_period is not None:
        return by_period
    if bill.amount_varies and fallback_to_estimate:
        # The document carries no period of its own, so it is most likely the
        # pending estimate; a confirmed instance must never be overwritten.
        return (
            query.filter(PaymentInstance.amount_estimated.is_(True))
            .order_by(PaymentInstance.due_date)
            .first()
        )
    return None


def confirm_draft(
    db: Session,
    draft: ImportDraft,
    *,
    bill_id: int | None = None,
    account_id: int | None = None,
    ad_hoc: bool = False,
    label: str | None = None,
) -> dict[str, Any]:
    """Apply a draft: set the instance amount, create the period's instance, or create an ad-hoc instance."""
    if draft.amount is None or draft.amount <= 0:
        raise ValueError("Draft has no amount to confirm")

    resolved_account_id: int | None = None
    if account_id is not None:
        resolved_account_id = get_account_for_user(db, draft.user_id, account_id).id

    user = db.get(User, draft.user_id)
    local_today = user_today(user.timezone if user else None)

    if ad_hoc and bill_id is None:
        resolved_label = (label or draft.provider or "").strip()
        if not resolved_label:
            raise ValueError("A label is required for an ad-hoc payment")
        due_date = draft.due_date
        if due_date is None:
            raise ValueError("A due date is required for an ad-hoc payment")
        period = due_date.strftime("%Y-%m")
        ad_hoc_instance = PaymentInstance(
            bill_id=None,
            user_id=draft.user_id,
            account_id=resolved_account_id,
            label=resolved_label,
            period=period,
            due_date=due_date,
            amount=draft.amount,
            amount_estimated=False,
            status=PaymentStatus.upcoming,
        )
        db.add(ad_hoc_instance)
        db.flush()
        recalculate_instance(ad_hoc_instance, today=local_today)
        draft.matched_bill_id = None
        draft.status = ImportStatus.confirmed
        draft.processed_at = _now()
        db.commit()
        db.refresh(ad_hoc_instance)
        db.refresh(draft)
        return {
            "draft_id": draft.id,
            "bill_id": None,
            "instance_id": ad_hoc_instance.id,
            "created_instance": True,
        }

    target_bill_id = bill_id if bill_id is not None else draft.matched_bill_id
    if target_bill_id is None:
        raise ValueError("No bill selected for this draft")
    bill = db.get(BillTemplate, target_bill_id)
    if bill is None or bill.user_id != draft.user_id or bill.is_deleted:
        raise ValueError("Bill not found")

    # App-wide invariant: an instance's period is its due date's month.
    # The document's billing period can disagree with the due date (e.g. an
    # August usage period billed on 15 October), so the due date wins.
    period = (
        draft.due_date.strftime("%Y-%m")
        if draft.due_date
        else (draft.period or local_today.strftime("%Y-%m"))
    )
    # An explicit or future period is a distinct bill: only fall back to a
    # pending estimate when the document has no period and is not future-dated.
    fallback_to_estimate = draft.period is None and period <= local_today.strftime(
        "%Y-%m"
    )
    instance = _target_instance(
        db,
        bill,
        period,
        due_date=draft.due_date,
        fallback_to_estimate=fallback_to_estimate,
    )
    created = False
    if instance is None:
        if bill.frequency == BillFrequency.weekly:
            due_date = draft.due_date
            if due_date is None:
                raise ValueError("Cannot determine the due date for this weekly bill")
        else:
            due_date = draft.due_date or _due_date_for_period(period, bill.due_day)
        if due_date is None:
            raise ValueError("Cannot determine the due date for this period")
        existing = (
            db.query(PaymentInstance)
            .filter(
                PaymentInstance.bill_id == bill.id,
                PaymentInstance.due_date == due_date,
            )
            .first()
        )
        if existing is not None:
            if existing.is_deleted:
                raise ValueError("This period was deleted for the bill")
            instance = existing
        else:
            instance = PaymentInstance(
                bill_id=bill.id,
                user_id=bill.user_id,
                account_id=resolved_account_id,
                period=period,
                due_date=due_date,
                amount=draft.amount,
                amount_estimated=False,
                status=PaymentStatus.upcoming,
            )
            db.add(instance)
            db.flush()
            created = True
    elif instance.status == PaymentStatus.paid:
        raise ValueError("The matching instance is already paid")

    instance.amount = draft.amount
    instance.amount_estimated = False
    if resolved_account_id is not None:
        instance.account_id = resolved_account_id
    recalculate_instance(instance)

    draft.matched_bill_id = bill.id
    draft.status = ImportStatus.confirmed
    draft.processed_at = _now()
    db.commit()
    db.refresh(instance)
    db.refresh(draft)
    return {
        "draft_id": draft.id,
        "bill_id": bill.id,
        "instance_id": instance.id,
        "created_instance": created,
    }


def discard_draft(db: Session, draft: ImportDraft) -> None:
    draft.status = ImportStatus.discarded
    draft.processed_at = _now()
    db.commit()


def _archive(path: Path, keep: bool) -> None:
    if not keep:
        path.unlink(missing_ok=True)
        return
    processed_dir = path.parent / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    path.replace(processed_dir / path.name)


def _fail_file(path: Path, error: Exception) -> None:
    failed_dir = path.parent / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)
    target = failed_dir / path.name
    path.replace(target)
    target.with_suffix(target.suffix + ".error").write_text(
        str(error), encoding="utf-8"
    )


def poll_directory(db: Session) -> dict[str, Any]:
    """Process every supported file in the watched directory once."""
    if not app_settings.import_enabled(db):
        return {"processed": 0, "skipped": "folder polling is disabled"}
    user = resolve_import_user(db)
    if user is None:
        return {
            "processed": 0,
            "error": "Set IMPORT_USER_EMAIL (or have exactly one account) for polled imports",
        }

    directory = app_settings.import_dir(db)
    error = app_settings.validate_import_dir(directory)
    if error:
        return {"processed": 0, "error": error}

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    processed = duplicates = failed = 0
    root_resolved = root.resolve()
    for path in sorted(root.iterdir()):
        if path.is_symlink():
            continue
        if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        try:
            resolved = path.resolve()
            if root_resolved not in resolved.parents and resolved != root_resolved:
                continue
        except OSError:
            continue
        try:
            if path.stat().st_size > _max_bytes():
                raise ValueError(
                    f"File exceeds IMPORT_MAX_FILE_MB ({settings.import_max_file_mb})"
                )
            data = path.read_bytes()
            result = import_document_drafts(
                db,
                user_id=user.id,
                data=data,
                filename=path.name,
                content_type=None,
                source=ImportSource.directory,
            )
        except Exception as exc:  # noqa: BLE001 — per-file tolerance
            logger.warning("Directory import failed for %s: %s", path.name, exc)
            _fail_file(path, exc)
            failed += 1
            continue
        if not result.drafts:
            duplicates += 1
        else:
            processed += len(result.drafts)
            duplicates += result.skipped_duplicates
        _archive(path, settings.import_keep_files)
    return {"processed": processed, "duplicates": duplicates, "failed": failed}


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (ValueError, UnicodeDecodeError):
        return value


def _message_drafts(
    db: Session, user: User, raw: bytes
) -> tuple[list[ImportDraft], int]:
    """Create drafts from one raw email; returns (drafts, skipped) counts."""
    message: Message = email.message_from_bytes(raw)
    sender = parseaddr(message.get("From", ""))[1].lower()
    allowed = app_settings.imap_allowed_senders(db)
    if allowed and sender not in {s.lower() for s in allowed}:
        return [], 0

    message_id = message.get("Message-ID") or _hash(raw)
    subject = _decode_header(message.get("Subject"))
    drafts: list[ImportDraft] = []
    skipped = 0
    part_index = 0
    text_body: str | None = None
    html_body: str | None = None
    had_attachment = False
    errors: list[str] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type().lower()
        disp_type = (part.get_content_disposition() or "").lower()
        raw_filename = _decode_header(part.get_filename()) or None

        if disp_type != "attachment" and content_type == "text/plain":
            if text_body is None:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    text_body = payload.decode(
                        part.get_content_charset() or "utf-8", "replace"
                    )
            continue
        if disp_type != "attachment" and content_type == "text/html":
            if html_body is None:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    html_body = payload.decode(
                        part.get_content_charset() or "utf-8", "replace"
                    )
            continue

        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            continue

        detected_type = _detect_document_content_type(
            content_type, raw_filename, payload
        )
        if detected_type is None:
            continue

        # Inline or un-dispositioned images (logos, signatures) are never bill attachments.
        if detected_type.startswith("image/") and disp_type != "attachment":
            continue

        had_attachment = True
        filename = raw_filename or f"email-part-{part_index}"
        ref = f"email:{message_id}:{part_index}"
        part_index += 1
        try:
            draft = _import_email_document(
                db, user, payload, filename, detected_type, ref
            )
        except Exception as exc:  # noqa: BLE001 — continue inspecting remaining parts
            logger.warning(
                "Email attachment import failed for %s (%s): %s",
                filename,
                message_id,
                exc,
            )
            errors.append(f"{filename}: {exc}")
            continue
        if draft is None:
            skipped += 1
        else:
            drafts.append(draft)

    # Afterpay / BNPL extraction when enabled
    if not had_attachment and app_settings.imap_afterpay_enabled(db):
        combined_text = (html_body or "") + "\n" + (text_body or "")
        if is_afterpay_email(sender, subject, combined_text):
            ref_date = user_today(user.timezone)
            bnpl = parse_afterpay(
                html_body or "", text_body or "", reference_date=ref_date
            )
            if bnpl is None:
                llm = app_settings.llm_config(db)
                if llm is not None:
                    bnpl = extract_bnpl_from_text(
                        combined_text, config=llm, reference_date=ref_date
                    )
            if bnpl is not None:
                ref = f"email:{message_id}:afterpay"
                extracted = ExtractedBill(
                    provider=f"Afterpay: {bnpl.merchant}",
                    amount=bnpl.installment_amount,
                    currency=bnpl.currency,
                    due_date=bnpl.start_date,
                    period=bnpl.start_date.strftime("%Y-%m"),
                    raw_text=html_body or text_body or "",
                    confidence=1.0,
                )
                draft = create_draft(
                    db,
                    user_id=user.id,
                    source=ImportSource.email,
                    source_ref=ref,
                    filename=None,
                    extracted=extracted,
                    meta=bnpl.to_dict(),
                )
                if draft is None:
                    return [], 1
                return [draft], 0

    # Fall back to plain text, or stripped HTML text, when no document attachment existed.
    if not had_attachment:
        body_text = (
            text_body.strip()
            if text_body and text_body.strip()
            else (_html_to_text(html_body) if html_body else "")
        )
        if body_text:
            ref = f"email:{message_id}:text"
            try:
                draft = import_text(
                    db,
                    user_id=user.id,
                    text=body_text,
                    source_ref=ref,
                    filename=None,
                    source=ImportSource.email,
                )
            except Exception as exc:  # noqa: BLE001 — record visible failure
                errors.append(str(exc))
            else:
                if draft is None:
                    skipped += 1
                else:
                    drafts.append(draft)

    if not drafts and skipped == 0:
        reason = (
            "; ".join(errors)
            if errors
            else "Email contained no supported bill attachment or extractable body text"
        )
        record_failed_draft(
            db,
            user_id=user.id,
            source=ImportSource.email,
            source_ref=f"email:{message_id}:failed",
            filename=subject or None,
            error=reason,
        )
        raise ValueError(reason)

    return drafts, skipped


def _import_email_document(
    db: Session,
    user: User,
    payload: bytes,
    filename: str,
    content_type: str,
    source_ref: str,
) -> ImportDraft | None:
    if len(payload) > _max_bytes():
        raise ValueError("Attachment exceeds IMPORT_MAX_FILE_MB")
    if _has_active_draft(db, source_ref):
        return None
    config = app_settings.llm_config(db)
    if config is None:
        raise LlmUnavailable("No LLM provider is configured (set one up in Settings)")
    extracted = extract_document(
        payload,
        config=config,
        content_type=content_type,
        filename=filename,
        reference_date=user_today(user.timezone),
    )
    return create_draft(
        db,
        user_id=user.id,
        source=ImportSource.email,
        source_ref=source_ref,
        filename=filename,
        extracted=extracted,
    )


def poll_email(db: Session) -> dict[str, Any]:
    """Process unseen messages in the configured IMAP folder once."""
    if not app_settings.imap_configured(db):
        return {"processed": 0, "skipped": "IMAP is not configured"}
    user = resolve_import_user(db)
    if user is None:
        return {
            "processed": 0,
            "error": "Set IMPORT_USER_EMAIL (or have exactly one account) for polled imports",
        }

    host = app_settings.imap_host(db) or ""
    port = app_settings.imap_port(db)
    username = app_settings.imap_user(db) or ""
    password = app_settings.imap_password(db) or ""
    use_tls = app_settings.imap_tls(db)
    folder = app_settings.imap_folder(db)
    mark_read = app_settings.imap_mark_read(db)
    if use_tls:
        connection: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            host, port, timeout=_IMAP_TIMEOUT_SECONDS
        )
    else:
        connection = imaplib.IMAP4(host, port, timeout=_IMAP_TIMEOUT_SECONDS)

    processed = skipped = failed = 0
    try:
        connection.login(username, password)
        connection.select(folder)
        status, data = connection.search(None, "UNSEEN")
        if status != "OK":
            return {"processed": 0, "error": f"IMAP search failed: {status}"}
        for num in (data[0] or b"").split():
            num_str = num.decode() if isinstance(num, bytes) else str(num)
            status, fetched = connection.fetch(num_str, "(RFC822)")
            if status != "OK" or not fetched:
                failed += 1
                continue
            entry = fetched[0]
            raw = entry[1] if isinstance(entry, tuple) else None
            if not isinstance(raw, bytes):
                failed += 1
                continue
            try:
                drafts, dupes = _message_drafts(db, user, raw)
                processed += len(drafts)
                skipped += dupes
            except Exception as exc:  # noqa: BLE001 — per-message tolerance
                logger.warning("Email import failed for message %s: %s", num, exc)
                failed += 1
            if mark_read:
                connection.store(num_str, "+FLAGS", "\\Seen")
    finally:
        try:
            connection.logout()
        except imaplib.IMAP4.error:  # pragma: no cover — best-effort close
            pass
    return {"processed": processed, "duplicates": skipped, "failed": failed}


_last_poll: dict[str, float] = {}


def _due(name: str, minutes: int, now: float) -> bool:
    last = _last_poll.get(name, 0.0)
    if now - last < minutes * 60:
        return False
    _last_poll[name] = now
    return True


def poll_directory_tick(db: Session, *, now: float | None = None) -> None:
    """Scheduler tick: run the folder poller when its interval has elapsed."""
    import time

    moment = time.monotonic() if now is None else now
    if not _due("directory", app_settings.import_poll_minutes(db), moment):
        return
    poll_directory(db)


def poll_email_tick(db: Session, *, now: float | None = None) -> None:
    """Scheduler tick: run the email poller when its interval has elapsed."""
    import time

    moment = time.monotonic() if now is None else now
    if not app_settings.imap_configured(db):
        return
    if not _due("email", app_settings.imap_poll_minutes(db), moment):
        return
    poll_email(db)


def poll_directory_job(session_factory: sessionmaker) -> None:
    """APScheduler entrypoint: open a fresh Session for the directory poll tick."""
    db: Session = session_factory()
    try:
        poll_directory_tick(db)
    finally:
        db.close()


def poll_email_job(session_factory: sessionmaker) -> None:
    """APScheduler entrypoint: open a fresh Session for the email poll tick."""
    db: Session = session_factory()
    try:
        poll_email_tick(db)
    finally:
        db.close()


def reset_poll_timers() -> None:
    """Test helper: forget when each poller last ran."""
    _last_poll.clear()
