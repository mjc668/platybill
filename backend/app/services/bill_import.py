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
from datetime import date, datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezones import user_today
from app.models.bill import BillFrequency, BillTemplate, PaymentInstance, PaymentStatus
from app.models.import_draft import ImportDraft, ImportSource, ImportStatus
from app.models.user import User
from app.services import app_settings
from app.services.bill_extract import ExtractedBill, extract_document, extract_from_text
from app.services.ollama import OllamaUnavailable
from app.services.payments import recalculate_instance
from app.services.recurrence import _due_date_for_period

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg"}
MATCH_THRESHOLD = 0.5
_IMAP_TIMEOUT_SECONDS = 30.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokens(value: str) -> set[str]:
    return {
        t
        for t in "".join(c.lower() if c.isalnum() else " " for c in value).split()
        if len(t) > 2
    }


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


def match_bill(db: Session, user_id: int, extracted: ExtractedBill) -> int | None:
    """Best token-overlap match of the provider against active bill names."""
    if not extracted.provider:
        return None
    provider_tokens = _tokens(extracted.provider)
    if not provider_tokens:
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
    best_id: int | None = None
    best_score = 0.0
    for bill in bills:
        overlap = provider_tokens & _tokens(bill.name)
        if not overlap:
            continue
        score = len(overlap) / len(provider_tokens)
        if score > best_score:
            best_id, best_score = bill.id, score
    return best_id if best_score >= MATCH_THRESHOLD else None


def create_draft(
    db: Session,
    *,
    user_id: int,
    source: ImportSource,
    source_ref: str,
    filename: str | None,
    extracted: ExtractedBill,
) -> ImportDraft | None:
    """Insert a draft unless `source_ref` was already imported (any status)."""
    existing = (
        db.query(ImportDraft).filter(ImportDraft.source_ref == source_ref).first()
    )
    if existing is not None:
        return None
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
        matched_bill_id=match_bill(db, user_id, extracted),
        status=ImportStatus.pending,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _max_bytes() -> int:
    return settings.import_max_file_mb * 1024 * 1024


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
    if len(data) > _max_bytes():
        raise ValueError(
            f"File exceeds IMPORT_MAX_FILE_MB ({settings.import_max_file_mb})"
        )
    source_ref = f"{source.value}:{_hash(data)}"
    if (
        db.query(ImportDraft).filter(ImportDraft.source_ref == source_ref).first()
        is not None
    ):
        return None
    config = app_settings.ollama_config(db)
    if config is None:
        raise OllamaUnavailable("Ollama is not configured (set the URL in Settings)")
    extracted = extract_document(
        data, config=config, content_type=content_type, filename=filename
    )
    return create_draft(
        db,
        user_id=user_id,
        source=source,
        source_ref=source_ref,
        filename=filename,
        extracted=extracted,
    )


def import_text(
    db: Session,
    *,
    user_id: int,
    text: str,
    source_ref: str,
    filename: str | None,
    source: ImportSource,
) -> ImportDraft | None:
    config = app_settings.ollama_config(db)
    if config is None:
        raise OllamaUnavailable("Ollama is not configured (set the URL in Settings)")
    extracted = extract_from_text(text, config=config)
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
    fallback_to_estimate: bool = False,
) -> PaymentInstance | None:
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
    db: Session, draft: ImportDraft, *, bill_id: int | None = None
) -> dict[str, Any]:
    """Apply a draft: set the instance amount, or create the period's instance."""
    target_bill_id = bill_id if bill_id is not None else draft.matched_bill_id
    if target_bill_id is None:
        raise ValueError("No bill selected for this draft")
    bill = db.get(BillTemplate, target_bill_id)
    if bill is None or bill.user_id != draft.user_id or bill.is_deleted:
        raise ValueError("Bill not found")
    if draft.amount is None or draft.amount <= 0:
        raise ValueError("Draft has no amount to confirm")

    # App-wide invariant: an instance's period is its due date's month.
    # The document's billing period can disagree with the due date (e.g. an
    # August usage period billed on 15 October), so the due date wins.
    user = db.get(User, draft.user_id)
    local_today = user_today(user.timezone if user else None)
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
        db, bill, period, fallback_to_estimate=fallback_to_estimate
    )
    created = False
    if instance is None:
        if bill.frequency == BillFrequency.weekly:
            raise ValueError("No matching instance for this weekly bill")
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
            if root_resolved not in path.resolve().parents and path.resolve() != root_resolved:
                continue
        except OSError:
            continue
        try:
            data = path.read_bytes()
            draft = import_document(
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
        if draft is None:
            duplicates += 1
        else:
            processed += 1
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
    if settings.imap_allowed_senders and sender not in {
        s.lower() for s in settings.imap_allowed_senders
    }:
        return [], 0

    message_id = message.get("Message-ID") or _hash(raw)
    drafts: list[ImportDraft] = []
    skipped = 0
    part_index = 0
    text_body: str | None = None
    had_attachment = False

    for part in message.walk():
        content_type = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition or content_type in ALLOWED_CONTENT_TYPES:
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes) or not payload:
                continue
            if content_type not in ALLOWED_CONTENT_TYPES:
                continue
            had_attachment = True
            filename = _decode_header(part.get_filename()) or f"email-part-{part_index}"
            ref = f"email:{message_id}:{part_index}"
            part_index += 1
            draft = _import_email_document(
                db, user, payload, filename, content_type, ref
            )
            if draft is None:
                skipped += 1
            else:
                drafts.append(draft)
        elif content_type == "text/plain" and text_body is None:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                text_body = payload.decode(
                    part.get_content_charset() or "utf-8", "replace"
                )

    # Only fall back to the body when the message carried no document at all;
    # a deduped attachment must not spawn a second draft from the body text.
    if not had_attachment and text_body and text_body.strip():
        ref = f"email:{message_id}:text"
        draft = import_text(
            db,
            user_id=user.id,
            text=text_body,
            source_ref=ref,
            filename=None,
            source=ImportSource.email,
        )
        if draft is None:
            skipped += 1
        else:
            drafts.append(draft)
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
    if (
        db.query(ImportDraft).filter(ImportDraft.source_ref == source_ref).first()
        is not None
    ):
        return None
    config = app_settings.ollama_config(db)
    if config is None:
        raise OllamaUnavailable("Ollama is not configured (set the URL in Settings)")
    extracted = extract_document(
        payload, config=config, content_type=content_type, filename=filename
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
    if not settings.imap_configured:
        return {"processed": 0, "skipped": "IMAP is not configured"}
    user = resolve_import_user(db)
    if user is None:
        return {
            "processed": 0,
            "error": "Set IMPORT_USER_EMAIL (or have exactly one account) for polled imports",
        }

    host = settings.imap_host or ""
    password = (
        settings.imap_password.get_secret_value() if settings.imap_password else ""
    )
    if settings.imap_tls:
        connection: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            host, settings.imap_port, timeout=_IMAP_TIMEOUT_SECONDS
        )
    else:
        connection = imaplib.IMAP4(
            host, settings.imap_port, timeout=_IMAP_TIMEOUT_SECONDS
        )

    processed = skipped = failed = 0
    try:
        connection.login(settings.imap_user or "", password)
        connection.select(settings.imap_folder)
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
            if settings.imap_mark_read:
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
    if not settings.imap_configured:
        return
    if not _due("email", settings.imap_poll_minutes, moment):
        return
    poll_email(db)


def reset_poll_timers() -> None:
    """Test helper: forget when each poller last ran."""
    _last_poll.clear()
