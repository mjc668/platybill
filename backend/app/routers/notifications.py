"""Install-level notification channel settings (SMTP + Apprise).

Values live in `app_settings` (DB override → env). Secrets are write-only:
status responses carry `*_configured` booleans and masked usernames, never
passwords, keys, or target URLs.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import current_user
from app.core.ratelimit import rate_limited_by_user
from app.models.user import User
from app.schemas.notifications import (
    NotificationSettingsIn,
    NotificationSettingsOut,
)
from app.services import app_settings
from app.services.bill_import import resolve_import_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _status(db: Session) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        smtp_configured=app_settings.smtp_configured(db),
        smtp_host=app_settings.smtp_host(db),
        smtp_port=app_settings.smtp_port(db),
        smtp_user=app_settings.smtp_user(db),
        smtp_password_configured=bool(app_settings.smtp_password(db)),
        smtp_use_tls=app_settings.smtp_use_tls(db),
        smtp_from=app_settings.smtp_from(db),
        apprise_configured=app_settings.apprise_configured(db),
        apprise_base_url=app_settings.apprise_base_url(db),
        apprise_urls_configured=bool(app_settings.apprise_urls(db)),
        apprise_key_configured=bool(app_settings.apprise_key(db)),
        apprise_timeout_seconds=app_settings.apprise_timeout(db),
    )


def _guard(db: Session, me: User) -> None:
    """Same install-global rule as import settings: the import target account
    (or the sole account) owns process-wide settings."""
    target = resolve_import_user(db)
    if target is not None and target.id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the import target account can change notification settings",
        )


@router.get("/settings", response_model=NotificationSettingsOut)
def get_notification_settings(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    _guard(db, me)
    return _status(db)


@router.patch("/settings", response_model=NotificationSettingsOut)
def update_notification_settings(
    body: NotificationSettingsIn,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
    _rl: None = Depends(rate_limited_by_user("import")),
):
    _guard(db, me)
    if body.smtp is not None:
        smtp = body.smtp
        if smtp.host is not None:
            app_settings.set_value(
                db, app_settings.SMTP_HOST_KEY, smtp.host.strip() or None
            )
        if smtp.port is not None:
            app_settings.set_value(db, app_settings.SMTP_PORT_KEY, str(smtp.port))
        if smtp.user is not None:
            app_settings.set_value(
                db, app_settings.SMTP_USER_KEY, smtp.user.strip() or None
            )
        if smtp.password is not None:
            app_settings.set_value(
                db, app_settings.SMTP_PASSWORD_KEY, smtp.password or None
            )
        if smtp.use_tls is not None:
            app_settings.set_value(
                db, app_settings.SMTP_USE_TLS_KEY, "1" if smtp.use_tls else "0"
            )
        if smtp.from_addr is not None:
            app_settings.set_value(
                db, app_settings.SMTP_FROM_KEY, smtp.from_addr.strip() or None
            )
    if body.apprise is not None:
        apprise = body.apprise
        if apprise.base_url is not None:
            url = apprise.base_url.strip().rstrip("/")
            if url and not url.startswith(("http://", "https://")):
                raise HTTPException(
                    status_code=422, detail="URL must start with http:// or https://"
                )
            app_settings.set_value(db, app_settings.APPRISE_BASE_URL_KEY, url or None)
        if apprise.urls is not None:
            app_settings.set_value(
                db, app_settings.APPRISE_URLS_KEY, apprise.urls.strip() or None
            )
        if apprise.key is not None:
            app_settings.set_value(
                db, app_settings.APPRISE_KEY_KEY, apprise.key.strip() or None
            )
        if apprise.timeout_seconds is not None:
            app_settings.set_value(
                db, app_settings.APPRISE_TIMEOUT_KEY, str(apprise.timeout_seconds)
            )
    return _status(db)
