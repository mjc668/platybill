import calendar
import io
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import current_user
from app.core.ratelimit import rate_limited_by_user
from app.models.bill import (
    BillFrequency,
    BillTemplate,
    PaymentInstance,
    PaymentStatus,
)
from app.models.payment import Payment
from app.models.restore_snapshot import RestoreSnapshot
from app.models.user import User
from app.schemas.bill import (
    BackupInstance,
    BackupPayment,
    BackupPayload,
    ExportSummaryOut,
    RestoreSnapshotOut,
)
from app.services.categories import category_label, resolve_backup_value

router = APIRouter(prefix="/export", tags=["export"])

_COLUMNS = [
    "Bill",
    "Category",
    "Period",
    "Due Date",
    "Amount",
    "Currency",
    "Status",
    "Paid Amount",
    "Paid At",
    "Notes",
]


@router.get("/xlsx")
def export_xlsx(
    year: int = Query(default_factory=lambda: date.today().year, ge=2000, le=2100),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    instances = (
        db.query(PaymentInstance)
        .options(
            selectinload(PaymentInstance.template).selectinload(BillTemplate.category)
        )
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == me.id,
            BillTemplate.is_deleted.is_(False),
            PaymentInstance.period.startswith(f"{year}-"),
            PaymentInstance.is_deleted.is_(False),
        )
        .order_by(PaymentInstance.due_date)
        .all()
    )

    # Index instances by month number (1–12)
    language = me.language_preference
    by_month: dict[int, list[dict]] = {m: [] for m in range(1, 13)}
    for i in instances:
        month = int(i.period[5:7])
        by_month[month].append(
            {
                "Bill": i.template.name,
                "Category": category_label(language, i.template.category),
                "Period": i.period,
                "Due Date": i.due_date.isoformat(),
                "Amount": float(i.amount),
                "Currency": i.template.currency,
                "Status": i.status,
                "Paid Amount": float(i.paid_amount) if i.paid_amount else None,
                "Paid At": i.paid_at.isoformat() if i.paid_at else None,
                "Notes": i.notes,
            }
        )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for month in range(1, 13):
            sheet_name = f"{calendar.month_abbr[month]} {year}"
            rows = by_month[month]
            df = (
                pd.DataFrame(rows, columns=_COLUMNS)
                if rows
                else pd.DataFrame(columns=_COLUMNS)
            )
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            # Formula-injection guard: openpyxl infers data_type "f" for any
            # string starting with "=". Force those cells back to string type
            # so user-controlled bill names/notes are never executed.
            worksheet = writer.sheets[sheet_name]
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        cell.data_type = "s"
    buf.seek(0)

    filename = f"platybill-{year}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_backup_arrays(db: Session, user_id: int) -> dict:
    """Serialize a user's bill_templates/payment_instances into the backup shape
    shared by GET /export/json and the pre-restore snapshot."""
    templates = (
        db.query(BillTemplate)
        .options(selectinload(BillTemplate.category))
        .filter(BillTemplate.user_id == user_id)
        .all()
    )
    template_ids = [t.id for t in templates]
    instances = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id.in_(template_ids),
            PaymentInstance.is_deleted.is_(False),
        )
        .all()
        if template_ids
        else []
    )
    instance_ids = [i.id for i in instances]
    payments = (
        db.query(Payment)
        .filter(Payment.instance_id.in_(instance_ids))
        .order_by(Payment.instance_id, Payment.paid_on, Payment.id)
        .all()
        if instance_ids
        else []
    )
    return {
        "bill_templates": [
            {
                "id": t.id,
                "name": t.name,
                "category": t.category.key or t.category.name,
                "frequency": t.frequency,
                "interval_count": t.interval_count,
                "max_occurrences": t.max_occurrences,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "amount": float(t.amount),
                "amount_varies": t.amount_varies,
                "currency": t.currency,
                "due_day": t.due_day,
                "notes": t.notes,
                "is_archived": t.is_archived,
                "is_paused": t.is_paused,
                "is_deleted": t.is_deleted,
                "archived_at": t.archived_at.isoformat() if t.archived_at else None,
                "start_period": t.start_period,
                "created_at": t.created_at.isoformat(),
            }
            for t in templates
        ],
        "payment_instances": [
            {
                "id": i.id,
                "bill_id": i.bill_id,
                "period": i.period,
                "due_date": i.due_date.isoformat(),
                "amount": float(i.amount),
                "amount_estimated": i.amount_estimated,
                "status": i.status,
                "paid_at": i.paid_at.isoformat() if i.paid_at else None,
                "paid_amount": float(i.paid_amount) if i.paid_amount else None,
                "notes": i.notes,
                "created_at": i.created_at.isoformat(),
                "reminder_sent_upcoming": i.reminder_sent_upcoming,
                "reminder_sent_overdue": i.reminder_sent_overdue,
            }
            for i in instances
        ],
        "payments": [
            {
                "id": p.id,
                "instance_id": p.instance_id,
                "amount": float(p.amount),
                "paid_on": p.paid_on.isoformat(),
                "note": p.note,
                "created_at": p.created_at.isoformat(),
            }
            for p in payments
        ],
    }


@router.get("/json")
def export_json(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    payload = {
        "schema_version": 8,
        "exported_by": me.email,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        **_build_backup_arrays(db, me.id),
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="platybill-backup-{datetime.now(timezone.utc).date()}.json"'
        },
    )


@router.get("/summary", response_model=ExportSummaryOut)
def export_summary(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    template_ids = [
        t.id
        for t in db.query(BillTemplate.id).filter(BillTemplate.user_id == me.id).all()
    ]
    bill_count = len(template_ids)
    payment_count = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id.in_(template_ids),
            PaymentInstance.is_deleted.is_(False),
        )
        .count()
        if template_ids
        else 0
    )
    return ExportSummaryOut(bill_count=bill_count, payment_count=payment_count)


def _synthesize_payments(
    instances: list[BackupInstance],
) -> list[BackupPayment]:
    """Build one ledger event per paid instance for v2/v3 backups (and old
    restore snapshots) that predate the payments table."""
    synthesized: list[BackupPayment] = []
    for bi in instances:
        if bi.status != PaymentStatus.paid:
            continue
        paid_on = (
            datetime.fromisoformat(bi.paid_at).date()
            if bi.paid_at
            else date.fromisoformat(bi.due_date)
        )
        synthesized.append(
            BackupPayment(
                id=0,
                instance_id=bi.id,
                amount=bi.paid_amount if bi.paid_amount is not None else bi.amount,
                paid_on=paid_on.isoformat(),
                note=bi.notes,
                created_at=bi.paid_at or bi.created_at,
            )
        )
    return synthesized


def _apply_backup(db: Session, user_id: int, backup: BackupPayload) -> tuple[int, int]:
    """Destructively wipe a user's existing bill_templates/payment_instances/payments
    and re-insert the backup's contents. Shared by /restore and /restore-snapshot."""
    existing_ids = [
        t.id
        for t in db.query(BillTemplate.id).filter(BillTemplate.user_id == user_id).all()
    ]
    if existing_ids:
        existing_instance_ids = [
            row.id
            for row in db.query(PaymentInstance.id)
            .filter(PaymentInstance.bill_id.in_(existing_ids))
            .all()
        ]
        if existing_instance_ids:
            db.query(Payment).filter(
                Payment.instance_id.in_(existing_instance_ids)
            ).delete(synchronize_session=False)
        db.query(PaymentInstance).filter(
            PaymentInstance.bill_id.in_(existing_ids)
        ).delete(synchronize_session=False)
        db.query(BillTemplate).filter(BillTemplate.user_id == user_id).delete(
            synchronize_session=False
        )

    id_map: dict[int, int] = {}
    category_ids: dict[str | None, int] = {}
    for bt in backup.bill_templates:
        if bt.category not in category_ids:
            # Resolve per distinct value, case-insensitively; never deletes
            # the user's existing categories.
            category_ids[bt.category] = resolve_backup_value(
                db, user_id, bt.category
            ).id
        template_obj = BillTemplate(
            name=bt.name,
            category_id=category_ids[bt.category],
            frequency=BillFrequency(bt.frequency),
            interval_count=bt.interval_count,
            max_occurrences=bt.max_occurrences,
            start_date=date.fromisoformat(bt.start_date) if bt.start_date else None,
            amount=Decimal(str(bt.amount)),
            amount_varies=bt.amount_varies,
            currency=bt.currency,
            due_day=bt.due_day,
            notes=bt.notes,
            is_archived=bt.is_archived,
            is_paused=bt.is_paused,
            is_deleted=bt.is_deleted,
            archived_at=(
                datetime.fromisoformat(bt.archived_at) if bt.archived_at else None
            ),
            start_period=bt.start_period,
            user_id=user_id,
        )
        db.add(template_obj)
        db.flush()
        id_map[bt.id] = template_obj.id

    instance_map: dict[int, int] = {}
    for bi in backup.payment_instances:
        instance_obj = PaymentInstance(
            bill_id=id_map[bi.bill_id],
            period=bi.period,
            due_date=date.fromisoformat(bi.due_date),
            amount=Decimal(str(bi.amount)),
            amount_estimated=bi.amount_estimated,
            status=PaymentStatus(bi.status),
            paid_at=datetime.fromisoformat(bi.paid_at) if bi.paid_at else None,
            paid_amount=(
                Decimal(str(bi.paid_amount)) if bi.paid_amount is not None else None
            ),
            notes=bi.notes,
            reminder_sent_upcoming=bi.reminder_sent_upcoming,
            reminder_sent_overdue=bi.reminder_sent_overdue,
        )
        db.add(instance_obj)
        db.flush()
        instance_map[bi.id] = instance_obj.id

    payments = backup.payments or _synthesize_payments(backup.payment_instances)
    for bp in payments:
        db.add(
            Payment(
                instance_id=instance_map[bp.instance_id],
                amount=Decimal(str(bp.amount)),
                paid_on=date.fromisoformat(bp.paid_on),
                note=bp.note,
                created_at=datetime.fromisoformat(bp.created_at),
            )
        )

    return len(backup.bill_templates), len(backup.payment_instances)


@router.post("/restore")
def restore_json(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
    _rl: None = Depends(rate_limited_by_user("restore")),
):
    _ALLOWED_TYPES = ("application/json", "text/plain", "application/octet-stream")
    if file.content_type and file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")
    _MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB
    content = file.file.read(_MAX_UPLOAD + 1)
    if len(content) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Backup file too large (max 10 MB)")
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid JSON")
    except (ValueError, AttributeError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid backup file")

    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Invalid backup file")

    if raw.get("schema_version") not in {2, 3, 4, 5, 6, 7, 8}:
        raise HTTPException(status_code=422, detail="Unsupported schema version")

    try:
        backup = BackupPayload.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (ValueError, AttributeError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid backup file")

    template_ids_in_backup = {t.id for t in backup.bill_templates}
    orphaned = [
        i for i in backup.payment_instances if i.bill_id not in template_ids_in_backup
    ]
    if orphaned:
        raise HTTPException(
            status_code=422, detail="Backup contains orphaned payment instances"
        )

    instance_ids_in_backup = {i.id for i in backup.payment_instances}
    orphaned_payments = [
        p for p in backup.payments if p.instance_id not in instance_ids_in_backup
    ]
    if orphaned_payments:
        raise HTTPException(status_code=422, detail="Backup contains orphaned payments")

    has_existing_bills = (
        db.query(BillTemplate.id).filter(BillTemplate.user_id == me.id).first()
        is not None
    )
    if has_existing_bills:
        snapshot_payload = {
            "schema_version": 8,
            **_build_backup_arrays(db, me.id),
        }
        db.query(RestoreSnapshot).filter(RestoreSnapshot.user_id == me.id).delete(
            synchronize_session=False
        )
        db.add(RestoreSnapshot(user_id=me.id, payload=snapshot_payload))

    restored_templates, restored_instances = _apply_backup(db, me.id, backup)
    # Single commit for snapshot write + destructive delete + re-insert: if any
    # of it raises, nothing above commits — do not split this into multiple
    # commits, it would break the "abort restore on snapshot failure" guarantee.
    db.commit()

    return {
        "restored_templates": restored_templates,
        "restored_instances": restored_instances,
    }


def _active_snapshot(db: Session, user_id: int) -> RestoreSnapshot | None:
    """The user's snapshot if one exists and is still within the retention
    window. Shared by /last-snapshot and /restore-snapshot so they can't
    drift on what counts as "expired"."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.restore_snapshot_retention_days
    )
    return (
        db.query(RestoreSnapshot)
        .filter(
            RestoreSnapshot.user_id == user_id, RestoreSnapshot.created_at >= cutoff
        )
        .first()
    )


@router.get("/last-snapshot", response_model=RestoreSnapshotOut)
def last_snapshot(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    snapshot = _active_snapshot(db, me.id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No recoverable snapshot")
    return RestoreSnapshotOut(created_at=snapshot.created_at)


@router.post("/restore-snapshot")
def restore_from_snapshot(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    snapshot = _active_snapshot(db, me.id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No snapshot to restore")

    try:
        backup = BackupPayload.model_validate(snapshot.payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (ValueError, AttributeError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid snapshot payload")
    restored_templates, restored_instances = _apply_backup(db, me.id, backup)
    db.delete(snapshot)
    db.commit()

    return {
        "restored_templates": restored_templates,
        "restored_instances": restored_instances,
    }
