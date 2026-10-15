"""Unit tests for app/services/reminder_job.py."""

import logging
import smtplib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


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
from app.services.reminder_job import (
    send_catchup_reminders,
    send_daily_reminders,
    send_monthly_summary_for_user,
    send_upcoming_digest_for_user,
)


def _make_user(
    db,
    email="u@test.com",
    notify_2_days_before=False,
    notify_1_day_before=True,
    notify_on_day=False,
    notify_1_day_after=False,
    reminder_send_minute=480,
) -> User:
    user = User(
        email=email,
        password_hash="x",
        is_active=True,
        email_reminders_enabled=True,
        notify_2_days_before=notify_2_days_before,
        notify_1_day_before=notify_1_day_before,
        notify_on_day=notify_on_day,
        notify_1_day_after=notify_1_day_after,
        reminder_send_minute=reminder_send_minute,
    )
    db.add(user)
    db.flush()
    return user


def _default_category(db, user_id: int) -> Category:
    category = (
        db.query(Category)
        .filter(Category.user_id == user_id, Category.key == "utilities")
        .first()
    )
    if category is None:
        category = Category(user_id=user_id, key="utilities")
        db.add(category)
        db.flush()
    return category


def _make_bill(db, user_id: int) -> BillTemplate:
    bill = BillTemplate(
        name="Internet",
        frequency=BillFrequency.monthly,
        amount=Decimal("99.99"),
        currency="PLN",
        category_id=_default_category(db, user_id).id,
        user_id=user_id,
    )
    db.add(bill)
    db.flush()
    return bill


def _make_instance(db, bill_id: int, due_date: date, **kwargs) -> PaymentInstance:
    kwargs.setdefault("status", PaymentStatus.upcoming)
    inst = PaymentInstance(
        bill_id=bill_id,
        period=due_date.strftime("%Y-%m"),
        due_date=due_date,
        amount=Decimal("99.99"),
        **kwargs,
    )
    db.add(inst)
    db.flush()
    return inst


@contextmanager
def _channels(
    *,
    smtp_host: str | None = "smtp.test",
    apprise_base_url: str | None = None,
    apprise_urls: str | None = None,
    apprise_key: str | None = None,
):
    """Patch the settings singleton so both reminder_job and notifications see it."""
    with (
        patch.object(settings, "smtp_host", smtp_host),
        patch.object(settings, "smtp_port", 587),
        patch.object(settings, "smtp_user", None),
        patch.object(settings, "smtp_password", None),
        patch.object(settings, "smtp_use_tls", True),
        patch.object(settings, "reminder_from", "r@test.com"),
        patch.object(settings, "email_blocked_domains", []),
        patch.object(settings, "apprise_base_url", apprise_base_url),
        patch.object(settings, "apprise_urls", apprise_urls),
        patch.object(settings, "apprise_key", apprise_key),
    ):
        yield


# ---------------------------------------------------------------------------


@patch("app.services.reminder_job.send_reminder_email")
def test_no_smtp_skips_all(mock_send, db_sessionmaker):
    with _channels(smtp_host=None):
        send_daily_reminders(db_sessionmaker)

    mock_send.assert_not_called()


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_upcoming_instance_sends_and_flips_flag(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=True)
    bill = _make_bill(db_session, user.id)
    inst = _make_instance(db_session, bill.id, due_date=today + timedelta(days=1))
    inst_id = inst.id
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["kind"] == "upcoming"

    db_session.expire_all()
    refreshed = db_session.get(PaymentInstance, inst_id)
    assert refreshed.reminder_sent_upcoming is True
    assert refreshed.reminder_sent_overdue is False


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_reminder_logs_email_masked(
    mock_send, _mock_summary, db_session, db_sessionmaker, caplog
):
    today = _today_utc()
    user = _make_user(db_session, email="alice@example.com", notify_1_day_before=True)
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=today + timedelta(days=1))
    db_session.commit()

    with (
        _channels(),
        caplog.at_level(logging.INFO, logger="app.services.reminder_job"),
    ):
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_called_once()
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "a***@example.com" in messages
    assert "alice@example.com" not in messages


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_1_day_after_instance_sends_and_flips_flag(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=False, notify_1_day_after=True)
    bill = _make_bill(db_session, user.id)
    inst = _make_instance(db_session, bill.id, due_date=today - timedelta(days=1))
    inst_id = inst.id
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["kind"] == "1_day_after"

    db_session.expire_all()
    refreshed = db_session.get(PaymentInstance, inst_id)
    assert refreshed.reminder_sent_overdue is True
    assert refreshed.reminder_sent_upcoming is False


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_2_days_before_instance_sends_and_flips_flag(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=False, notify_2_days_before=True)
    bill = _make_bill(db_session, user.id)
    inst = _make_instance(db_session, bill.id, due_date=today + timedelta(days=2))
    inst_id = inst.id
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["kind"] == "2_days_before"

    db_session.expire_all()
    refreshed = db_session.get(PaymentInstance, inst_id)
    assert refreshed.reminder_sent_2_days_before is True


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_on_day_instance_sends_and_flips_flag(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=False, notify_on_day=True)
    bill = _make_bill(db_session, user.id)
    inst = _make_instance(db_session, bill.id, due_date=today)
    inst_id = inst.id
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["kind"] == "on_day"

    db_session.expire_all()
    refreshed = db_session.get(PaymentInstance, inst_id)
    assert refreshed.reminder_sent_on_day is True


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_weekly_instances_fire_per_due_date(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    """Two occurrences of one weekly bill carry independent reminder flags."""
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=True, notify_on_day=True)
    bill = BillTemplate(
        name="Weekly",
        frequency=BillFrequency.weekly,
        interval_count=1,
        start_date=today,
        amount=Decimal("10.00"),
        currency="PLN",
        category_id=_default_category(db_session, user.id).id,
        user_id=user.id,
    )
    db_session.add(bill)
    db_session.flush()
    due_today = _make_instance(db_session, bill.id, due_date=today)
    due_tomorrow = _make_instance(
        db_session, bill.id, due_date=today + timedelta(days=1)
    )
    today_id, tomorrow_id = due_today.id, due_tomorrow.id
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    assert mock_send.call_count == 2

    db_session.expire_all()
    refreshed_today = db_session.get(PaymentInstance, today_id)
    refreshed_tomorrow = db_session.get(PaymentInstance, tomorrow_id)
    assert refreshed_today.reminder_sent_on_day is True
    assert refreshed_today.reminder_sent_upcoming is False
    assert refreshed_tomorrow.reminder_sent_upcoming is True
    assert refreshed_tomorrow.reminder_sent_on_day is False


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_already_sent_flag_skips_email(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=True)
    bill = _make_bill(db_session, user.id)
    _make_instance(
        db_session,
        bill.id,
        due_date=today + timedelta(days=1),
        reminder_sent_upcoming=True,
    )
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_not_called()


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_opt_out_user_skips_email(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    today = _today_utc()
    user = _make_user(
        db_session,
        notify_2_days_before=False,
        notify_1_day_before=False,
        notify_on_day=False,
        notify_1_day_after=False,
    )
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=today + timedelta(days=1))
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_not_called()


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_reminder_email")
def test_smtp_exception_does_not_flip_flag(
    mock_send, _mock_summary, db_session, db_sessionmaker
):
    import smtplib

    mock_send.side_effect = smtplib.SMTPException("connection refused")

    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=True)
    bill = _make_bill(db_session, user.id)
    inst = _make_instance(db_session, bill.id, due_date=today + timedelta(days=1))
    inst_id = inst.id
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_called_once()

    db_session.expire_all()
    refreshed = db_session.get(PaymentInstance, inst_id)
    assert refreshed.reminder_sent_upcoming is False
    assert refreshed.reminder_sent_overdue is False


# ---------------------------------------------------------------------------
# Monthly summary service tests
# ---------------------------------------------------------------------------


def _make_paid_instance(db, bill_id: int, due_date: date, **kwargs) -> PaymentInstance:
    from datetime import datetime, timezone

    inst = PaymentInstance(
        bill_id=bill_id,
        period=due_date.strftime("%Y-%m"),
        due_date=due_date,
        amount=Decimal("99.99"),
        paid_amount=Decimal("99.99"),
        status=PaymentStatus.paid,
        paid_at=datetime.now(timezone.utc),
        **kwargs,
    )
    db.add(inst)
    db.flush()
    return inst


def _make_bill_named(db, user_id: int, name: str) -> BillTemplate:
    bill = BillTemplate(
        name=name,
        frequency=BillFrequency.monthly,
        amount=Decimal("99.99"),
        currency="PLN",
        category_id=_default_category(db, user_id).id,
        user_id=user_id,
    )
    db.add(bill)
    db.flush()
    return bill


@patch("app.services.reminder_job.send_monthly_summary_email")
def test_monthly_summary_splits_paid_and_unpaid(mock_send, db_session):
    today = _today_utc()
    user = _make_user(db_session)
    paid_bill = _make_bill_named(db_session, user.id, "Internet")
    unpaid_bill = _make_bill_named(db_session, user.id, "Netflix")
    _make_paid_instance(db_session, paid_bill.id, due_date=today.replace(day=1))
    _make_instance(db_session, unpaid_bill.id, due_date=today.replace(day=5))
    db_session.commit()

    with _channels():
        result = send_monthly_summary_for_user(
            db_session, user, today.strftime("%Y-%m")
        )

    assert result is True
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert len(kwargs["paid_rows"]) == 1
    assert len(kwargs["unpaid_rows"]) == 1
    assert kwargs["paid_rows"][0]["name"] == "Internet"
    assert kwargs["unpaid_rows"][0]["name"] == "Netflix"


def test_monthly_summary_returns_false_when_smtp_not_configured(db_session):
    user = _make_user(db_session)
    db_session.commit()

    with _channels(smtp_host=None):
        result = send_monthly_summary_for_user(db_session, user, "2026-06")

    assert result is False


@patch("app.services.reminder_job.send_monthly_summary_email")
def test_monthly_summary_returns_false_on_smtp_error(mock_send, db_session):
    mock_send.side_effect = smtplib.SMTPException("connection refused")

    today = _today_utc()
    user = _make_user(db_session)
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=today)
    db_session.commit()

    with _channels():
        result = send_monthly_summary_for_user(
            db_session, user, today.strftime("%Y-%m")
        )

    assert result is False


@patch("app.services.reminder_job.send_monthly_summary_email")
def test_monthly_summary_idempotency_via_last_sent_flag(
    mock_send, db_session, db_sessionmaker
):
    """Scheduler skips user whose monthly_summary_last_sent matches current month."""
    import calendar
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    today = _today_utc()
    current_month = today.strftime("%Y-%m")

    user = _make_user(db_session)
    # Pre-set the flag as if the summary was already sent this month
    user.monthly_summary_enabled = True
    user.monthly_summary_last_sent = current_month
    db_session.commit()

    # Simulate last day of month
    last_day = calendar.monthrange(today.year, today.month)[1]
    fake_today = today.replace(day=last_day)

    with (
        _channels(),
        patch(
            "app.services.reminder_job.datetime",
            wraps=__import__("datetime", fromlist=["datetime"]).datetime,
        ) as mock_dt,
    ):
        mock_dt.now.return_value = datetime(
            fake_today.year, fake_today.month, fake_today.day, 8, 0, tzinfo=timezone.utc
        )
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_not_called()


@patch("app.services.reminder_job.send_monthly_summary_email")
def test_monthly_summary_sent_and_flag_updated_on_last_day(
    mock_send, db_session, db_sessionmaker
):
    """Scheduler sends summary and sets flag when last_sent is None."""
    import calendar
    from datetime import datetime, timezone

    today = _today_utc()
    last_day = calendar.monthrange(today.year, today.month)[1]
    fake_today = today.replace(day=last_day)

    user = _make_user(db_session)
    user.monthly_summary_enabled = True
    user.monthly_summary_last_sent = None
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=fake_today)
    db_session.commit()
    user_id = user.id

    with (
        _channels(),
        patch(
            "app.services.reminder_job.datetime",
            wraps=__import__("datetime", fromlist=["datetime"]).datetime,
        ) as mock_dt,
    ):
        mock_dt.now.return_value = datetime(
            fake_today.year, fake_today.month, fake_today.day, 8, 0, tzinfo=timezone.utc
        )
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_called_once()
    db_session.expire_all()
    refreshed_user = db_session.get(User, user_id)
    assert refreshed_user.monthly_summary_last_sent == fake_today.strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Master toggle: email_reminders_enabled=False must block all sends
# ---------------------------------------------------------------------------


@patch("app.services.reminder_job.send_reminder_email")
def test_master_toggle_off_skips_daily_reminder(mock_send, db_session, db_sessionmaker):
    """Scheduler sends nothing when email_reminders_enabled is False."""
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=True)
    user.email_reminders_enabled = False
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=today + timedelta(days=1))
    db_session.commit()

    with _channels():
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_not_called()


@patch("app.services.reminder_job.send_reminder_email")
def test_master_toggle_off_skips_catchup_reminder(
    mock_send, db_session, db_sessionmaker
):
    """Catch-up reminders on startup also respect email_reminders_enabled=False."""
    today = _today_utc()
    user = _make_user(db_session, notify_1_day_before=True, reminder_send_minute=0)
    user.email_reminders_enabled = False
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=today + timedelta(days=1))
    db_session.commit()

    with _channels():
        # current_minute=480 covers all users whose send_minute <= 480
        send_catchup_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_not_called()


@patch("app.services.reminder_job.send_monthly_summary_email")
def test_master_toggle_off_skips_monthly_summary_scheduler(
    mock_send, db_session, db_sessionmaker
):
    """Monthly summary scheduler respects email_reminders_enabled=False."""
    import calendar
    from datetime import datetime, timezone

    today = _today_utc()
    last_day = calendar.monthrange(today.year, today.month)[1]
    fake_today = today.replace(day=last_day)

    user = _make_user(db_session)
    user.email_reminders_enabled = False
    user.monthly_summary_enabled = True
    user.monthly_summary_last_sent = None
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=fake_today)
    db_session.commit()

    with (
        _channels(),
        patch(
            "app.services.reminder_job.datetime",
            wraps=__import__("datetime", fromlist=["datetime"]).datetime,
        ) as mock_dt,
    ):
        mock_dt.now.return_value = datetime(
            fake_today.year, fake_today.month, fake_today.day, 8, 0, tzinfo=timezone.utc
        )
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Weekly due-preview digest
# ---------------------------------------------------------------------------


@patch("app.services.reminder_job.send_upcoming_digest_email")
def test_digest_classifies_rows_by_local_day_and_window(mock_send, db_session):
    """Overdue vs upcoming is decided in the user's timezone; window is N days."""
    # 23:30 UTC is already the 16th in Kiritimati (UTC+14) but still the 15th
    # in UTC — the digest must use the user's local day.
    fixed_now = datetime(2026, 10, 15, 23, 30, tzinfo=timezone.utc)
    user = _make_user(db_session)
    user.timezone = "Pacific/Kiritimati"
    user.upcoming_digest_enabled = True
    user.upcoming_digest_days = 7
    bill = _make_bill(db_session, user.id)

    _make_instance(db_session, bill.id, due_date=date(2026, 10, 15))  # local overdue
    _make_instance(db_session, bill.id, due_date=date(2026, 10, 16))  # local today
    _make_instance(db_session, bill.id, due_date=date(2026, 10, 22))  # inside window
    _make_instance(db_session, bill.id, due_date=date(2026, 10, 23))  # at boundary: out
    _make_instance(
        db_session, bill.id, due_date=date(2026, 10, 17), status=PaymentStatus.paid
    )
    _make_instance(
        db_session, bill.id, due_date=date(2026, 10, 18), amount_estimated=True
    )
    _make_instance(db_session, bill.id, due_date=date(2026, 10, 19), is_deleted=True)
    db_session.commit()

    with _channels():
        result = send_upcoming_digest_for_user(db_session, user, now_utc=fixed_now)

    assert result is True
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["days"] == 7
    assert [r["due_date"] for r in kwargs["overdue_rows"]] == ["2026-10-15"]
    assert [r["due_date"] for r in kwargs["upcoming_rows"]] == [
        "2026-10-16",
        "2026-10-22",
    ]


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_upcoming_digest_email")
def test_daily_job_sends_digest_once_on_matching_local_slot(
    mock_digest, mock_summary, db_session, db_sessionmaker
):
    """The scheduler sends on the chosen weekday/minute, once per local day."""
    today = _today_utc()
    user = _make_user(db_session)
    user.upcoming_digest_enabled = True
    user.upcoming_digest_weekday = today.weekday()
    user.upcoming_digest_minute = 480
    bill = _make_bill(db_session, user.id)
    _make_instance(db_session, bill.id, due_date=today + timedelta(days=3))
    db_session.commit()
    user_id = user.id

    with (
        _channels(),
        patch(
            "app.services.reminder_job.datetime",
            wraps=__import__("datetime", fromlist=["datetime"]).datetime,
        ) as mock_dt,
    ):
        mock_dt.now.return_value = datetime(
            today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc
        )
        send_daily_reminders(db_sessionmaker, send_minute=480)
        mock_digest.assert_called_once()

        db_session.expire_all()
        assert db_session.get(User, user_id).upcoming_digest_last_sent == (
            today.isoformat()
        )

        # A later tick on the same local day must not resend.
        mock_digest.reset_mock()
        send_daily_reminders(db_sessionmaker, send_minute=600)
        mock_digest.assert_not_called()


@patch("app.services.reminder_job.send_monthly_summary_email")
@patch("app.services.reminder_job.send_upcoming_digest_email")
def test_digest_not_sent_on_other_weekdays_or_when_disabled(
    mock_digest, mock_summary, db_session, db_sessionmaker
):
    today = _today_utc()
    wrong_day_user = _make_user(db_session, email="wrongday@test.com")
    wrong_day_user.upcoming_digest_enabled = True
    wrong_day_user.upcoming_digest_weekday = (today.weekday() + 1) % 7
    wrong_day_user.upcoming_digest_minute = 0
    disabled_user = _make_user(db_session, email="disabled@test.com")
    disabled_user.upcoming_digest_enabled = False
    disabled_user.upcoming_digest_weekday = today.weekday()
    db_session.commit()

    with (
        _channels(),
        patch(
            "app.services.reminder_job.datetime",
            wraps=__import__("datetime", fromlist=["datetime"]).datetime,
        ) as mock_dt,
    ):
        mock_dt.now.return_value = datetime(
            today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc
        )
        send_daily_reminders(db_sessionmaker, send_minute=480)

    mock_digest.assert_not_called()
