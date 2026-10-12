"""Bill import endpoints: upload, draft review, confirm, status, manual scans."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import current_user
from app.core.ratelimit import rate_limited_by_user
from app.models.bill import BillTemplate
from app.models.import_draft import ImportDraft, ImportSource, ImportStatus
from app.models.user import User
from app.schemas.imports import (
    ImportConfirmIn,
    ImportConfirmOut,
    ImportDraftOut,
    ImportDraftUpdate,
    ImportSettingsIn,
    ImportStatusOut,
    ScanNowOut,
    TestOllamaOut,
)
from app.services import app_settings, ollama
from app.services.bill_import import (
    ALLOWED_CONTENT_TYPES,
    confirm_draft,
    discard_draft,
    import_document,
    poll_directory,
    poll_email,
)

router = APIRouter(prefix="/import", tags=["import"])


def _draft_out(draft: ImportDraft) -> ImportDraftOut:
    out = ImportDraftOut.model_validate(draft)
    if draft.matched_bill is not None:
        out = out.model_copy(update={"matched_bill_name": draft.matched_bill.name})
    return out


def _scoped_draft(db: Session, draft_id: int, me: User) -> ImportDraft:
    draft = (
        db.query(ImportDraft)
        .options(selectinload(ImportDraft.matched_bill))
        .filter(ImportDraft.id == draft_id, ImportDraft.user_id == me.id)
        .first()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Import draft not found")
    return draft


def _mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value
    local, _, domain = value.partition("@")
    return f"{local[:1]}***@{domain}"


@router.post(
    "/upload",
    response_model=ImportDraftOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_bill(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
    _rl: None = Depends(rate_limited_by_user("import")),
):
    if not settings.ollama_configured:
        raise HTTPException(
            status_code=503,
            detail="Bill import is not configured (set OLLAMA_BASE_URL)",
        )
    content_type = file.content_type
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    max_bytes = settings.import_max_file_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.import_max_file_mb} MB)",
        )
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")

    try:
        draft = import_document(
            db,
            user_id=me.id,
            data=data,
            filename=file.filename,
            content_type=content_type,
            source=ImportSource.upload,
        )
    except ollama.OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ollama.OllamaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if draft is None:
        raise HTTPException(status_code=409, detail="This file was already imported")
    return _draft_out(draft)


@router.get("/drafts", response_model=list[ImportDraftOut])
def list_drafts(
    status_filter: str = Query("pending", alias="status"),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    query = (
        db.query(ImportDraft)
        .options(selectinload(ImportDraft.matched_bill))
        .filter(ImportDraft.user_id == me.id)
    )
    if status_filter != "all":
        try:
            query = query.filter(ImportDraft.status == ImportStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown status filter")
    drafts = query.order_by(ImportDraft.created_at.desc()).limit(100).all()
    return [_draft_out(draft) for draft in drafts]


@router.patch("/drafts/{draft_id}", response_model=ImportDraftOut)
def update_draft(
    draft_id: int,
    body: ImportDraftUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    draft = _scoped_draft(db, draft_id, me)
    if draft.status != ImportStatus.pending:
        raise HTTPException(status_code=400, detail="Draft is no longer pending")

    updates = body.model_dump(exclude_unset=True)
    bill_id = updates.pop("matched_bill_id", None)
    if bill_id is not None:
        bill = db.get(BillTemplate, bill_id)
        if bill is None or bill.user_id != me.id:
            raise HTTPException(status_code=404, detail="Bill not found")
        draft.matched_bill_id = bill.id
    for field, value in updates.items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    return _draft_out(draft)


@router.post("/drafts/{draft_id}/confirm", response_model=ImportConfirmOut)
def confirm_import_draft(
    draft_id: int,
    body: ImportConfirmIn,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    draft = _scoped_draft(db, draft_id, me)
    if draft.status != ImportStatus.pending:
        raise HTTPException(status_code=400, detail="Draft is no longer pending")
    try:
        result = confirm_draft(db, draft, bill_id=body.bill_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportConfirmOut(**result)


@router.post("/drafts/{draft_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
def discard_import_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    draft = _scoped_draft(db, draft_id, me)
    discard_draft(db, draft)


def _status(db: Session, me: User) -> ImportStatusOut:
    reachable = False
    model_available: bool | None = None
    if settings.ollama_configured:
        try:
            models = ollama.list_models()
            reachable = True
            model_available = settings.ollama_model in models
        except ollama.OllamaError:
            reachable = False

    pending_count = (
        db.query(ImportDraft)
        .filter(
            ImportDraft.user_id == me.id,
            ImportDraft.status == ImportStatus.pending,
        )
        .count()
    )
    last_failed = (
        db.query(ImportDraft)
        .filter(
            ImportDraft.user_id == me.id,
            ImportDraft.status == ImportStatus.failed,
        )
        .order_by(ImportDraft.created_at.desc())
        .first()
    )
    return ImportStatusOut(
        ollama_configured=settings.ollama_configured,
        ollama_reachable=reachable,
        ollama_model=settings.ollama_model,
        model_available=model_available,
        import_enabled=app_settings.import_enabled(db),
        import_dir=app_settings.import_dir(db),
        import_poll_minutes=app_settings.import_poll_minutes(db),
        imap_configured=settings.imap_configured,
        imap_user=_mask_email(settings.imap_user),
        pending_count=pending_count,
        last_error=last_failed.error if last_failed else None,
    )


@router.get("/status", response_model=ImportStatusOut)
def import_status(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    return _status(db, me)


@router.patch("/settings", response_model=ImportStatusOut)
def update_import_settings(
    body: ImportSettingsIn,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
    _rl: None = Depends(rate_limited_by_user("import")),
):
    if body.directory is not None:
        error = app_settings.validate_import_dir(body.directory)
        if error:
            raise HTTPException(status_code=422, detail=error)
        app_settings.set_value(db, app_settings.IMPORT_DIR_KEY, body.directory)
    if body.enabled is not None:
        app_settings.set_value(
            db, app_settings.IMPORT_ENABLED_KEY, "1" if body.enabled else "0"
        )
    if body.poll_minutes is not None:
        app_settings.set_value(
            db, app_settings.IMPORT_POLL_MINUTES_KEY, str(body.poll_minutes)
        )
    return _status(db, me)


@router.post("/test-ollama", response_model=TestOllamaOut)
def test_ollama(
    _rl: None = Depends(rate_limited_by_user("import")),
):
    if not settings.ollama_configured:
        return TestOllamaOut(
            ok=False,
            model=settings.ollama_model,
            model_available=False,
            error="Ollama is not configured (set OLLAMA_BASE_URL)",
        )
    try:
        models = ollama.list_models()
    except ollama.OllamaError as exc:
        return TestOllamaOut(
            ok=False,
            model=settings.ollama_model,
            model_available=False,
            error=str(exc),
        )
    return TestOllamaOut(
        ok=True,
        model=settings.ollama_model,
        model_available=settings.ollama_model in models,
    )


@router.post("/scan-now", response_model=ScanNowOut)
def scan_now(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
    _rl: None = Depends(rate_limited_by_user("import")),
):
    return ScanNowOut(
        directory=poll_directory(db),
        email=poll_email(db),
    )
