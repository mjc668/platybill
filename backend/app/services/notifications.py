import logging
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

import httpx
from sqlalchemy.orm import Session

from app.services import app_settings

logger = logging.getLogger(__name__)


class NotificationChannel(str, Enum):
    apprise = "apprise"
    email = "email"


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    channel: NotificationChannel | None = None
    error: str | None = None
    # Which channel produced `error` (None for configuration errors); lets
    # callers redact channel-specific diagnostics before returning them.
    source: NotificationChannel | None = None


def apprise_configured(db: Session) -> bool:
    return app_settings.apprise_configured(db)


def any_channel_configured(db: Session) -> bool:
    return apprise_configured(db) or app_settings.smtp_configured(db)


def send_via_apprise(
    db: Session, *, title: str, body: str, notify_type: str = "info"
) -> DeliveryResult:
    if not apprise_configured(db):
        return DeliveryResult(
            ok=False,
            error="apprise not configured",
            source=NotificationChannel.apprise,
        )

    base_url = (app_settings.apprise_base_url(db) or "").rstrip("/")
    if app_settings.apprise_key(db):
        url = f"{base_url}/notify/{app_settings.apprise_key(db)}"
        payload: dict[str, str | None] = {
            "title": title,
            "body": body,
            "type": notify_type,
        }
    else:
        url = f"{base_url}/notify"
        payload = {
            "title": title,
            "body": body,
            "type": notify_type,
        }
        # Omit `urls` when unset so the gateway falls back to its own
        # APPRISE_STATELESS_URLS configuration.
        if app_settings.apprise_urls(db):
            payload["urls"] = app_settings.apprise_urls(db)

    try:
        response = httpx.post(
            url, json=payload, timeout=app_settings.apprise_timeout(db)
        )
    except httpx.HTTPError as exc:
        return DeliveryResult(
            ok=False, error=str(exc), source=NotificationChannel.apprise
        )

    if response.is_success:
        return DeliveryResult(ok=True, channel=NotificationChannel.apprise)
    snippet = " ".join(response.text.split())[:300]
    detail = f"apprise HTTP {response.status_code}"
    if snippet:
        detail = f"{detail}: {snippet}"
    return DeliveryResult(ok=False, error=detail, source=NotificationChannel.apprise)


def deliver(
    db: Session,
    *,
    title: str,
    body: str,
    notify_type: str,
    email_sender: Callable[[], None],
) -> DeliveryResult:
    apprise_result: DeliveryResult | None = None
    if apprise_configured(db):
        apprise_result = send_via_apprise(
            db, title=title, body=body, notify_type=notify_type
        )
        if apprise_result.ok:
            return apprise_result
        logger.warning(
            "Apprise delivery failed (%s); falling back to email",
            apprise_result.error,
        )

    if app_settings.smtp_configured(db):
        try:
            email_sender()
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("Email delivery failed: %s", exc)
            return DeliveryResult(
                ok=False, error=str(exc), source=NotificationChannel.email
            )
        return DeliveryResult(ok=True, channel=NotificationChannel.email)

    if apprise_result is not None:
        logger.warning(
            "Apprise delivery failed and no email channel is configured: %s",
            apprise_result.error,
        )
        return apprise_result
    return DeliveryResult(ok=False, error="no notification channel configured")
