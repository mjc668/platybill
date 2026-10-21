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
    TestImapOut,
    TestOllamaOut,
)
from app.services import app_settings
from app.services.bill_import import (
    ALLOWED_CONTENT_TYPES,
    confirm_draft,
    discard_draft,
    import_document,
    poll_directory,
    poll_email,
    resolve_import_user,
)
from app.services.llm import LlmError, LlmUnavailable

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
    if app_settings.llm_config(db) is None:
        raise HTTPException(
            status_code=503,
            detail="Bill import is not configured (set up an LLM provider in Settings)",
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
    except LlmUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LlmError as exc:
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
    from app.services import llm as llm_client

    # Legacy Ollama fields stay populated so old frontends keep working.
    legacy = app_settings.ollama_config(db)
    llm = app_settings.llm_config(db)
    provider = app_settings.llm_provider(db)
    reachable = False
    model_available: bool | None = None
    available_models: list[str] = []
    if llm is not None:
        try:
            available_models = llm_client.list_models(config=llm)
            reachable = True
            model_available = llm.model in available_models
        except llm_client.LlmError:
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
        ollama_configured=legacy is not None,
        ollama_base_url=legacy.base_url if legacy is not None else None,
        ollama_reachable=reachable and provider == "ollama",
        ollama_model=legacy.model if legacy is not None else settings.ollama_model,
        model_available=model_available,
        available_models=available_models,
        llm_provider=provider,
        llm_model=llm.model if llm is not None else app_settings.llm_model(db),
        llm_base_url=llm.base_url if llm is not None else None,
        llm_configured=llm is not None,
        llm_api_key_configured=bool(app_settings.llm_api_key(db)),
        import_enabled=app_settings.import_enabled(db),
        import_dir=app_settings.import_dir(db),
        import_poll_minutes=app_settings.import_poll_minutes(db),
        imap_configured=app_settings.imap_configured(db),
        imap_user=_mask_email(app_settings.imap_user(db)),
        imap_host=app_settings.imap_host(db),
        imap_port=app_settings.imap_port(db),
        imap_folder=app_settings.imap_folder(db),
        imap_tls=app_settings.imap_tls(db),
        imap_poll_minutes=app_settings.imap_poll_minutes(db),
        imap_mark_read=app_settings.imap_mark_read(db),
        imap_password_configured=bool(app_settings.imap_password(db)),
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
    # Import settings are process-wide: only the account that polled imports
    # target (or the sole account) may change them.
    target = resolve_import_user(db)
    if target is not None and target.id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the import target account can change import settings",
        )
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
    if body.ollama_base_url is not None:
        url = body.ollama_base_url.rstrip("/")
        error = app_settings.validate_ollama_url(url)
        if error:
            raise HTTPException(status_code=422, detail=error)
        app_settings.set_value(db, app_settings.OLLAMA_BASE_URL_KEY, url)
    if body.ollama_model is not None:
        model = body.ollama_model.strip()
        if not model:
            raise HTTPException(status_code=422, detail="Model must not be empty")
        app_settings.set_value(db, app_settings.OLLAMA_MODEL_KEY, model)
    if body.llm_provider is not None:
        from app.services.llm import PROVIDERS

        provider = body.llm_provider.strip().lower()
        if provider not in PROVIDERS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown provider '{body.llm_provider}'",
            )
        app_settings.set_value(db, app_settings.LLM_PROVIDER_KEY, provider)
    if body.llm_model is not None:
        model = body.llm_model.strip()
        if not model:
            raise HTTPException(status_code=422, detail="Model must not be empty")
        app_settings.set_value(db, app_settings.LLM_MODEL_KEY, model)
    if body.llm_base_url is not None:
        url = body.llm_base_url.strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422, detail="URL must start with http:// or https://"
            )
        app_settings.set_value(db, app_settings.LLM_BASE_URL_KEY, url or None)
    if body.llm_api_key is not None:
        app_settings.set_value(
            db, app_settings.LLM_API_KEY_KEY, body.llm_api_key or None
        )
    if body.llm_timeout_seconds is not None:
        app_settings.set_value(
            db, app_settings.LLM_TIMEOUT_KEY, str(body.llm_timeout_seconds)
        )
    if body.imap_host is not None:
        app_settings.set_value(
            db, app_settings.IMAP_HOST_KEY, body.imap_host.strip() or None
        )
    if body.imap_port is not None:
        app_settings.set_value(db, app_settings.IMAP_PORT_KEY, str(body.imap_port))
    if body.imap_user is not None:
        app_settings.set_value(
            db, app_settings.IMAP_USER_KEY, body.imap_user.strip() or None
        )
    if body.imap_password is not None:
        app_settings.set_value(
            db, app_settings.IMAP_PASSWORD_KEY, body.imap_password or None
        )
    if body.imap_folder is not None:
        folder = body.imap_folder.strip()
        if not folder:
            raise HTTPException(status_code=422, detail="Folder must not be empty")
        app_settings.set_value(db, app_settings.IMAP_FOLDER_KEY, folder)
    if body.imap_tls is not None:
        app_settings.set_value(
            db, app_settings.IMAP_TLS_KEY, "1" if body.imap_tls else "0"
        )
    if body.imap_poll_minutes is not None:
        app_settings.set_value(
            db, app_settings.IMAP_POLL_MINUTES_KEY, str(body.imap_poll_minutes)
        )
    if body.imap_mark_read is not None:
        app_settings.set_value(
            db, app_settings.IMAP_MARK_READ_KEY, "1" if body.imap_mark_read else "0"
        )
    if body.imap_allowed_senders is not None:
        app_settings.set_value(
            db, app_settings.IMAP_ALLOWED_SENDERS_KEY, body.imap_allowed_senders
        )
    return _status(db, me)


@router.post("/test-ollama", response_model=TestOllamaOut)
def test_ollama(
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limited_by_user("import")),
):
    from app.services import llm as llm_client

    config = app_settings.llm_config(db)
    if config is None:
        return TestOllamaOut(
            ok=False,
            model=app_settings.llm_model(db),
            model_available=False,
            error="No LLM provider is configured (set one up in Settings)",
        )
    try:
        models = llm_client.list_models(config=config)
    except llm_client.LlmError as exc:
        return TestOllamaOut(
            ok=False,
            model=config.model,
            model_available=False,
            error=str(exc),
        )
    return TestOllamaOut(
        ok=True,
        model=config.model,
        model_available=config.model in models,
    )


@router.get("/imap-folders", response_model=list[str])
def list_imap_folders(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
    _rl: None = Depends(rate_limited_by_user("import")),
):
    """List mailbox folders via IMAP LIST (names only, no secrets echoed)."""
    import imaplib

    target = resolve_import_user(db)
    if target is not None and target.id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the import target account can change import settings",
        )
    if not app_settings.imap_configured(db):
        raise HTTPException(status_code=400, detail="IMAP is not configured")
    host = app_settings.imap_host(db) or ""
    try:
        if app_settings.imap_tls(db):
            connection: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                host, app_settings.imap_port(db), timeout=15
            )
        else:
            connection = imaplib.IMAP4(host, app_settings.imap_port(db), timeout=15)
        try:
            connection.login(
                app_settings.imap_user(db) or "",
                app_settings.imap_password(db) or "",
            )
            ok, data = connection.list()
            if ok != "OK" or not data:
                raise HTTPException(status_code=502, detail="IMAP LIST failed")
            folders: list[str] = []
            for entry in data:
                raw = entry.decode() if isinstance(entry, bytes) else str(entry)
                name = raw.split(' "/" ', 1)[-1].strip().strip('"')
                if name:
                    folders.append(name)
            return sorted(set(folders))
        finally:
            try:
                connection.logout()
            except imaplib.IMAP4.error:  # pragma: no cover — best-effort close
                pass
    except HTTPException:
        raise
    except (imaplib.IMAP4.error, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"IMAP error: {exc}") from exc


@router.post("/test-imap", response_model=TestImapOut)
def test_imap(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
    _rl: None = Depends(rate_limited_by_user("import")),
):
    """Verify IMAP login + folder selection; returns folder + unseen count."""
    import imaplib

    target = resolve_import_user(db)
    if target is not None and target.id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the import target account can change import settings",
        )
    if not app_settings.imap_configured(db):
        return {"ok": False, "error": "IMAP is not configured"}
    host = app_settings.imap_host(db) or ""
    try:
        if app_settings.imap_tls(db):
            connection: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                host, app_settings.imap_port(db), timeout=15
            )
        else:
            connection = imaplib.IMAP4(host, app_settings.imap_port(db), timeout=15)
        try:
            connection.login(
                app_settings.imap_user(db) or "",
                app_settings.imap_password(db) or "",
            )
            ok, _ = connection.select(app_settings.imap_folder(db))
            if ok != "OK":
                return {
                    "ok": False,
                    "error": f"Cannot select folder '{app_settings.imap_folder(db)}'",
                }
            ok, data = connection.search(None, "UNSEEN")
            unseen = len((data[0] or b"").split()) if ok == "OK" else 0
            return {
                "ok": True,
                "folder": app_settings.imap_folder(db),
                "unseen": unseen,
            }
        finally:
            try:
                connection.logout()
            except imaplib.IMAP4.error:  # pragma: no cover — best-effort close
                pass
    except (imaplib.IMAP4.error, OSError) as exc:
        return {"ok": False, "error": f"IMAP error: {exc}"}


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
