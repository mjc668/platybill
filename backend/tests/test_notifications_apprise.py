"""Tests for the Apprise notification dispatcher (no network — httpx is mocked)."""

import smtplib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

import app.models.bill  # noqa: F401 — register models
import app.models.category  # noqa: F401
import app.models.user  # noqa: F401
from app.core.config import settings
from app.models.bill import (
    BillFrequency,
    BillTemplate,
    PaymentInstance,
    PaymentStatus,
)
from app.models.category import Category
from app.models.user import User
from app.services import notifications
from app.services.email import build_monthly_summary_text, build_reminder_text
from app.services.notifications import (
    NotificationChannel,
    deliver,
    send_via_apprise,
)
from app.services.reminder_job import (
    send_daily_reminders,
    send_monthly_summary_for_user,
)
from tests.conftest import auth, register_and_login

_PASSWORD = "pw123456"
_APPRISE_BASE = "http://apprise.test:8000"
_APPRISE_URLS = "ntfy://topic"


@contextmanager
def _channels(
    *,
    smtp_host: str | None = None,
    apprise_base_url: str | None = None,
    apprise_urls: str | None = None,
    apprise_key: str | None = None,
):
    with (
        patch.object(settings, "smtp_host", smtp_host),
        patch.object(settings, "apprise_base_url", apprise_base_url),
        patch.object(settings, "apprise_urls", apprise_urls),
        patch.object(settings, "apprise_key", apprise_key),
        patch.object(settings, "apprise_timeout_seconds", 10.0),
        patch.object(settings, "email_blocked_domains", []),
    ):
        yield


# ---------------------------------------------------------------------------
# send_via_apprise payloads
# ---------------------------------------------------------------------------


def test_send_via_apprise_stateless_payload(db_session):
    with (
        _channels(apprise_base_url=_APPRISE_BASE, apprise_urls=_APPRISE_URLS),
        patch(
            "app.services.notifications.httpx.post",
            return_value=httpx.Response(200, json={"success": True}),
        ) as mock_post,
    ):
        result = send_via_apprise(
            db_session, title="T", body="B", notify_type="warning"
        )

    assert result.ok is True
    assert result.channel == NotificationChannel.apprise
    assert result.error is None
    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == f"{_APPRISE_BASE}/notify"
    payload = mock_post.call_args.kwargs["json"]
    assert payload == {
        "urls": _APPRISE_URLS,
        "title": "T",
        "body": "B",
        "type": "warning",
    }


def test_send_via_apprise_key_payload_omits_urls(db_session):
    with (
        _channels(
            apprise_base_url=_APPRISE_BASE,
            apprise_urls=_APPRISE_URLS,
            apprise_key="household",
        ),
        patch(
            "app.services.notifications.httpx.post",
            return_value=httpx.Response(200),
        ) as mock_post,
    ):
        result = send_via_apprise(db_session, title="T", body="B")

    assert result.ok is True
    assert mock_post.call_args.args[0] == f"{_APPRISE_BASE}/notify/household"
    payload = mock_post.call_args.kwargs["json"]
    assert "urls" not in payload
    assert payload["type"] == "info"


def test_send_via_apprise_base_url_only_uses_gateway_config(db_session):
    """A gateway that holds its own targets needs only APPRISE_BASE_URL."""
    with (
        _channels(apprise_base_url=_APPRISE_BASE),
        patch(
            "app.services.notifications.httpx.post",
            return_value=httpx.Response(200),
        ) as mock_post,
    ):
        result = send_via_apprise(db_session, title="T", body="B")

    assert result.ok is True
    assert mock_post.call_args.args[0] == f"{_APPRISE_BASE}/notify"
    payload = mock_post.call_args.kwargs["json"]
    assert "urls" not in payload


def test_send_via_apprise_error_includes_response_snippet(db_session):
    with (
        _channels(apprise_base_url=_APPRISE_BASE, apprise_urls=_APPRISE_URLS),
        patch(
            "app.services.notifications.httpx.post",
            return_value=httpx.Response(424, text="Failed to send to ntfy://topic"),
        ),
    ):
        result = send_via_apprise(db_session, title="T", body="B")

    assert result.ok is False
    assert result.error is not None
    assert "424" in result.error
    assert "ntfy://topic" in result.error


def test_send_via_apprise_not_configured_does_not_call_httpx(db_session):
    with (
        _channels(),
        patch("app.services.notifications.httpx.post") as mock_post,
    ):
        result = send_via_apprise(db_session, title="T", body="B")

    assert result.ok is False
    assert result.channel is None
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# deliver — channel selection and fallback
# ---------------------------------------------------------------------------


def test_deliver_apprise_success_skips_email(db_session):
    email_sender = MagicMock()
    with (
        _channels(
            smtp_host="smtp.test",
            apprise_base_url=_APPRISE_BASE,
            apprise_urls=_APPRISE_URLS,
        ),
        patch(
            "app.services.notifications.httpx.post", return_value=httpx.Response(200)
        ),
    ):
        result = deliver(
            db_session,
            title="T",
            body="B",
            notify_type="info",
            email_sender=email_sender,
        )

    assert result.ok is True
    assert result.channel == NotificationChannel.apprise
    email_sender.assert_not_called()


def test_deliver_apprise_http_error_falls_back_to_email(db_session):
    email_sender = MagicMock()
    with (
        _channels(
            smtp_host="smtp.test",
            apprise_base_url=_APPRISE_BASE,
            apprise_urls=_APPRISE_URLS,
        ),
        patch(
            "app.services.notifications.httpx.post", return_value=httpx.Response(500)
        ),
    ):
        result = deliver(
            db_session,
            title="T",
            body="B",
            notify_type="info",
            email_sender=email_sender,
        )

    assert result.ok is True
    assert result.channel == NotificationChannel.email
    assert result.error is None
    email_sender.assert_called_once()


def test_deliver_apprise_timeout_falls_back_to_email(db_session):
    email_sender = MagicMock()
    with (
        _channels(
            smtp_host="smtp.test",
            apprise_base_url=_APPRISE_BASE,
            apprise_urls=_APPRISE_URLS,
        ),
        patch(
            "app.services.notifications.httpx.post",
            side_effect=httpx.ConnectTimeout("timed out"),
        ),
    ):
        result = deliver(
            db_session,
            title="T",
            body="B",
            notify_type="info",
            email_sender=email_sender,
        )

    assert result.ok is True
    assert result.channel == NotificationChannel.email
    email_sender.assert_called_once()


def test_deliver_apprise_failure_without_email_returns_error(db_session):
    email_sender = MagicMock()
    with (
        _channels(
            apprise_base_url=_APPRISE_BASE,
            apprise_urls=_APPRISE_URLS,
        ),
        patch(
            "app.services.notifications.httpx.post", return_value=httpx.Response(503)
        ),
    ):
        result = deliver(
            db_session,
            title="T",
            body="B",
            notify_type="info",
            email_sender=email_sender,
        )

    assert result.ok is False
    assert result.channel is None
    assert result.error == "apprise HTTP 503"
    email_sender.assert_not_called()


def test_deliver_email_failure_returns_error(db_session):
    def _boom() -> None:
        raise smtplib.SMTPException("connection refused")

    with _channels(smtp_host="smtp.test"):
        result = deliver(
            db_session, title="T", body="B", notify_type="info", email_sender=_boom
        )

    assert result.ok is False
    assert result.error == "connection refused"


def test_deliver_no_channel_configured(db_session):
    email_sender = MagicMock()
    with _channels():
        result = deliver(
            db_session,
            title="T",
            body="B",
            notify_type="info",
            email_sender=email_sender,
        )

    assert result.ok is False
    assert result.channel is None
    assert result.error == "no notification channel configured"
    email_sender.assert_not_called()


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------


def test_build_reminder_text_is_localized():
    title, body = build_reminder_text(
        bill_name="Internet",
        due_date=date(2026, 6, 17),
        amount=Decimal("99.99"),
        currency="PLN",
        kind="upcoming",
        language="pl",
    )
    assert title == "Przypomnienie: Internet płatne jutro (99.99 PLN)"
    assert "Internet" in body
    assert "2026-06-17" in body


def test_build_monthly_summary_text_is_compact_plain_text():
    title, body = build_monthly_summary_text(
        month_label="June 2026",
        paid_rows=[],
        unpaid_rows=[],
        language="en",
    )
    assert title == "Monthly summary for June 2026 — Platybill"
    assert "June 2026" in body
    assert "<html>" not in body


# ---------------------------------------------------------------------------
# Reminder job integration
# ---------------------------------------------------------------------------


def _make_reminder_fixture(db, email: str) -> tuple[User, int]:
    today = datetime.now(timezone.utc).date()
    due = today + timedelta(days=1)
    user = User(
        email=email,
        password_hash="x",
        is_active=True,
        email_reminders_enabled=True,
        notify_2_days_before=False,
        notify_1_day_before=True,
        notify_on_day=False,
        notify_1_day_after=False,
        reminder_send_minute=480,
        monthly_summary_enabled=False,
    )
    db.add(user)
    db.flush()
    category = Category(user_id=user.id, key="utilities")
    db.add(category)
    db.flush()
    bill = BillTemplate(
        name="Internet",
        frequency=BillFrequency.monthly,
        amount=Decimal("99.99"),
        currency="PLN",
        category_id=category.id,
        user_id=user.id,
    )
    db.add(bill)
    db.flush()
    instance = PaymentInstance(
        bill_id=bill.id,
        period=due.strftime("%Y-%m"),
        due_date=due,
        amount=Decimal("99.99"),
        status=PaymentStatus.upcoming,
    )
    db.add(instance)
    db.flush()
    instance_id = instance.id
    db.commit()
    return user, instance_id


def test_reminder_job_skips_when_no_channel_configured(db_sessionmaker):
    with (
        _channels(),
        patch("app.services.notifications.httpx.post") as mock_post,
        patch("app.services.reminder_job.send_reminder_email") as mock_email,
    ):
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_post.assert_not_called()
    mock_email.assert_not_called()


def test_reminder_via_apprise_sets_flag_without_email_sent_at(
    db_session, db_sessionmaker
):
    _user, instance_id = _make_reminder_fixture(db_session, "apprise@household.test")

    with (
        _channels(apprise_base_url=_APPRISE_BASE, apprise_urls=_APPRISE_URLS),
        patch(
            "app.services.notifications.httpx.post", return_value=httpx.Response(200)
        ) as mock_post,
        patch("app.services.reminder_job.send_reminder_email") as mock_email,
    ):
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_post.assert_called_once()
    mock_email.assert_not_called()

    db_session.expire_all()
    refreshed = db_session.get(PaymentInstance, instance_id)
    assert refreshed.reminder_sent_upcoming is True
    assert refreshed.email_sent_at is None


def test_reminder_via_email_sets_flag_and_email_sent_at(db_session, db_sessionmaker):
    _user, instance_id = _make_reminder_fixture(db_session, "email@household.test")

    with (
        _channels(smtp_host="smtp.test"),
        patch("app.services.reminder_job.send_reminder_email") as mock_email,
    ):
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_email.assert_called_once()
    db_session.expire_all()
    refreshed = db_session.get(PaymentInstance, instance_id)
    assert refreshed.reminder_sent_upcoming is True
    assert refreshed.email_sent_at is not None


def test_monthly_summary_uses_apprise_when_configured(db_session):
    today = datetime.now(timezone.utc).date()
    user = User(
        email="summary@household.test",
        password_hash="x",
        is_active=True,
        email_reminders_enabled=True,
        notify_1_day_before=True,
        reminder_send_minute=480,
    )
    db_session.add(user)
    db_session.flush()
    category = Category(user_id=user.id, key="utilities")
    db_session.add(category)
    db_session.flush()
    bill = BillTemplate(
        name="Internet",
        frequency=BillFrequency.monthly,
        amount=Decimal("99.99"),
        currency="PLN",
        category_id=category.id,
        user_id=user.id,
    )
    db_session.add(bill)
    db_session.flush()
    db_session.add(
        PaymentInstance(
            bill_id=bill.id,
            period=today.strftime("%Y-%m"),
            due_date=today,
            amount=Decimal("99.99"),
            status=PaymentStatus.upcoming,
        )
    )
    db_session.commit()

    with (
        _channels(apprise_base_url=_APPRISE_BASE, apprise_urls=_APPRISE_URLS),
        patch(
            "app.services.notifications.httpx.post", return_value=httpx.Response(200)
        ) as mock_post,
        patch("app.services.reminder_job.send_monthly_summary_email") as mock_email,
    ):
        result = send_monthly_summary_for_user(
            db_session, user, today.strftime("%Y-%m")
        )

    assert result is True
    mock_post.assert_called_once()
    mock_email.assert_not_called()


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


def test_notification_status_reflects_settings(client):
    token = register_and_login(client, "notif_status@test.com", _PASSWORD)
    with (
        _channels(smtp_host="smtp.test", apprise_base_url=_APPRISE_BASE),
        patch.object(settings, "apprise_urls", _APPRISE_URLS),
    ):
        r = client.get("/auth/notification-status", headers=auth(token))

    assert r.status_code == 200
    assert r.json() == {"smtp_configured": True, "apprise_configured": True}


def test_notification_status_requires_auth(client):
    r = client.get("/auth/notification-status")
    assert r.status_code == 401


def test_send_test_notification_apprise_failure_redacts_upstream_body(client):
    token = register_and_login(client, "test_apprise_fail@test.com", _PASSWORD)
    with (
        _channels(apprise_base_url=_APPRISE_BASE, apprise_urls=_APPRISE_URLS),
        patch(
            "app.services.notifications.httpx.post",
            return_value=httpx.Response(424, text="Failed to reach ntfy://secret"),
        ),
    ):
        r = client.post("/auth/send-test-notification", headers=auth(token))

    assert r.status_code == 200
    assert r.json()["ok"] is False
    detail = r.json()["detail"]
    assert detail is not None
    assert "apprise request failed" in detail
    assert "HTTP 424" in detail
    assert "ntfy://" not in detail
    assert "secret" not in detail


def test_notification_status_all_unconfigured(client):
    token = register_and_login(client, "notif_status_none@test.com", _PASSWORD)
    with _channels():
        r = client.get("/auth/notification-status", headers=auth(token))

    assert r.status_code == 200
    assert r.json() == {"smtp_configured": False, "apprise_configured": False}


def test_send_test_notification_via_apprise(client):
    token = register_and_login(client, "test_apprise@test.com", _PASSWORD)
    with (
        _channels(apprise_base_url=_APPRISE_BASE, apprise_urls=_APPRISE_URLS),
        patch(
            "app.services.notifications.httpx.post", return_value=httpx.Response(200)
        ) as mock_post,
    ):
        r = client.post("/auth/send-test-notification", headers=auth(token))

    assert r.status_code == 200
    assert r.json() == {"ok": True, "channel": "apprise", "detail": None}
    mock_post.assert_called_once()


def test_send_test_notification_falls_back_to_email(client):
    token = register_and_login(client, "test_email@test.com", _PASSWORD)
    with (
        _channels(
            smtp_host="smtp.test",
            apprise_base_url=_APPRISE_BASE,
            apprise_urls=_APPRISE_URLS,
        ),
        patch(
            "app.services.notifications.httpx.post", return_value=httpx.Response(500)
        ),
        patch("app.routers.auth.send_test_email") as mock_email,
    ):
        r = client.post("/auth/send-test-notification", headers=auth(token))

    assert r.status_code == 200
    assert r.json() == {"ok": True, "channel": "email", "detail": None}
    mock_email.assert_called_once()


def test_send_test_notification_none_configured(client):
    token = register_and_login(client, "test_none@test.com", _PASSWORD)
    with _channels():
        r = client.post("/auth/send-test-notification", headers=auth(token))

    assert r.status_code == 200
    assert r.json() == {
        "ok": False,
        "channel": None,
        "detail": "no notification channel configured",
    }


def test_send_notification_now_400_only_when_no_channel(client):
    token = register_and_login(client, "gate@test.com", _PASSWORD)

    with _channels():
        r = client.post("/auth/send-notification-now", headers=auth(token))
    assert r.status_code == 400
    assert r.json()["detail"] == "No notification channel configured"

    with (
        _channels(apprise_base_url=_APPRISE_BASE, apprise_urls=_APPRISE_URLS),
        patch("app.routers.auth.send_reminders_for_user", return_value=1) as mock_send,
    ):
        r = client.post("/auth/send-notification-now", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["sent"] == 1
    mock_send.assert_called_once()


@pytest.mark.parametrize(
    "language,expected_subject",
    [
        ("en", "Platybill test notification"),
        ("pl", "Powiadomienie testowe Platybill"),
        ("de", "Platybill Testbenachrichtigung"),
    ],
)
@patch("app.services.email.smtplib.SMTP")
def test_send_test_email_subject_per_language(
    mock_smtp_cls, language, expected_subject
):
    from app.services.email import send_test_email

    smtp_instance = MagicMock()
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=smtp_instance)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

    send_test_email(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user=None,
        smtp_password=None,
        from_addr="reminders@example.com",
        to_addr="user@example.com",
        language=language,
    )

    msg = smtp_instance.send_message.call_args[0][0]
    assert msg["Subject"] == expected_subject
