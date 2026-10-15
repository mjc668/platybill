import calendar
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.config import settings
from app.core.logging_utils import mask_email
from app.core.timezones import user_now, user_today
from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.models.user import User
from app.services import notifications
from app.services.email import (
    build_monthly_summary_text,
    build_reminder_text,
    build_upcoming_digest_text,
    send_monthly_summary_email,
    send_reminder_email,
    send_upcoming_digest_email,
)
from app.services.notifications import NotificationChannel

logger = logging.getLogger(__name__)


def _is_blocked_domain(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return domain in {d.lower() for d in settings.email_blocked_domains}


_MONTH_NAMES: dict[str, list[str]] = {
    "en": [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
    "pl": [
        "styczeń",
        "luty",
        "marzec",
        "kwiecień",
        "maj",
        "czerwiec",
        "lipiec",
        "sierpień",
        "wrzesień",
        "październik",
        "listopad",
        "grudzień",
    ],
    "de": [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ],
}


def _month_label(month: str, lang: str) -> str:
    """Return a human-readable month label, e.g. 'June 2026'."""
    year, m = month.split("-")
    names = _MONTH_NAMES.get(lang, _MONTH_NAMES["en"])
    return f"{names[int(m) - 1]} {year}"


def send_monthly_summary_for_user(db: Session, user: User, month: str) -> bool:
    """Send monthly summary for a single user. Returns True on success."""
    if not notifications.any_channel_configured():
        return False
    if _is_blocked_domain(user.email):
        logger.debug(
            "Skipping monthly summary for blocked domain: %s (user %s)",
            mask_email(user.email),
            user.id,
        )
        return False
    lang = user.language_preference or "en"
    instances = (
        db.query(PaymentInstance)
        .options(selectinload(PaymentInstance.template))
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user.id,
            PaymentInstance.period == month,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
        )
        .all()
    )

    paid_rows = []
    unpaid_rows = []
    for inst in instances:
        name = inst.template.name if inst.template else f"bill#{inst.bill_id}"
        currency = inst.template.currency if inst.template else "PLN"
        due_date = inst.due_date.isoformat() if inst.due_date else ""
        if inst.status == PaymentStatus.paid:
            paid_rows.append(
                {
                    "name": name,
                    "due_date": due_date,
                    "amount": inst.amount,
                    "paid_amount": inst.paid_amount,
                    "currency": currency,
                    "paid_at": inst.paid_at,
                }
            )
        else:
            unpaid_rows.append(
                {
                    "name": name,
                    "due_date": due_date,
                    "amount": inst.amount,
                    "currency": currency,
                }
            )

    month_label = _month_label(month, lang)
    title, body_text = build_monthly_summary_text(
        month_label=month_label,
        paid_rows=paid_rows,
        unpaid_rows=unpaid_rows,
        language=lang,
    )

    def _send_email() -> None:
        smtp_host = settings.smtp_host
        if smtp_host is None:
            raise OSError("SMTP not configured")
        send_monthly_summary_email(
            smtp_host=smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password=(
                settings.smtp_password.get_secret_value()
                if settings.smtp_password
                else None
            ),
            smtp_use_tls=settings.smtp_use_tls,
            from_addr=settings.reminder_from or settings.smtp_user or "",
            to_addr=user.email,
            month_label=month_label,
            paid_rows=paid_rows,
            unpaid_rows=unpaid_rows,
            language=lang,
        )

    result = notifications.deliver(
        title=title,
        body=body_text,
        notify_type="info",
        email_sender=_send_email,
    )
    if result.ok:
        logger.info(
            "Sent monthly summary to %s (user %s) for %s via %s",
            mask_email(user.email),
            user.id,
            month,
            result.channel.value if result.channel else "unknown",
        )
        return True
    logger.error(
        "Failed to send monthly summary to %s (user %s) for %s: %s",
        mask_email(user.email),
        user.id,
        month,
        result.error,
    )
    return False


def _local_minute(user: User, now_utc: datetime | None = None) -> int:
    """The user's current minute-of-day in their timezone (server-local unset)."""
    local_now = user_now(user.timezone, now_utc=now_utc)
    return local_now.hour * 60 + local_now.minute


def send_reminders_for_user(db: Session, user: User) -> int:
    """Send due reminders for a single user. Returns count of emails sent."""
    if _is_blocked_domain(user.email):
        logger.debug(
            "Skipping reminders for blocked domain: %s (user %s)",
            mask_email(user.email),
            user.id,
        )
        return 0
    # Reminder windows follow the user's local calendar day.
    today = user_today(user.timezone, now_utc=datetime.now(timezone.utc))
    tomorrow = today + timedelta(days=1)
    two_days_out = today + timedelta(days=2)
    yesterday = today - timedelta(days=1)

    template_ids = [
        t.id
        for t in db.query(BillTemplate.id)
        .filter(
            BillTemplate.user_id == user.id,
            BillTemplate.is_archived.is_(False),
            BillTemplate.is_deleted.is_(False),
            BillTemplate.is_paused.is_(False),
        )
        .all()
    ]
    if not template_ids:
        return 0

    lang = user.language_preference or "en"
    sent = 0

    windows: list[tuple[str, date, str]] = []
    if user.notify_2_days_before:
        windows.append(("2_days_before", two_days_out, "reminder_sent_2_days_before"))
    if user.notify_1_day_before:
        windows.append(("upcoming", tomorrow, "reminder_sent_upcoming"))
    if user.notify_on_day:
        windows.append(("on_day", today, "reminder_sent_on_day"))
    if user.notify_1_day_after:
        windows.append(("1_day_after", yesterday, "reminder_sent_overdue"))

    for kind, due, flag_attr in windows:
        instances = (
            db.query(PaymentInstance)
            .options(selectinload(PaymentInstance.template))
            .filter(
                PaymentInstance.bill_id.in_(template_ids),
                PaymentInstance.due_date == due,
                PaymentInstance.status != PaymentStatus.paid,
                PaymentInstance.is_deleted.is_(False),
                PaymentInstance.amount_estimated.is_(False),
                getattr(PaymentInstance, flag_attr).is_(False),
            )
            .all()
        )
        for instance in instances:
            if _send_and_flag(
                db, user, instance, kind=kind, flag_attr=flag_attr, language=lang
            ):
                sent += 1

    return sent


def send_upcoming_digest_for_user(
    db: Session, user: User, now_utc: datetime | None = None
) -> bool:
    """Send the weekly due-overview digest for a single user.

    Covers unpaid overdue rows plus everything due within the user's
    configured window (in their local timezone). Returns True on success.
    Archived, deleted and estimated instances stay out - the digest mirrors
    the Payments ledger.
    """
    if not notifications.any_channel_configured():
        return False
    if _is_blocked_domain(user.email):
        logger.debug(
            "Skipping due digest for blocked domain: %s (user %s)",
            mask_email(user.email),
            user.id,
        )
        return False

    today = user_today(user.timezone, now_utc=now_utc)
    window_end = today + timedelta(days=user.upcoming_digest_days)
    instances = (
        db.query(PaymentInstance)
        .options(selectinload(PaymentInstance.template))
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user.id,
            BillTemplate.is_archived.is_(False),
            BillTemplate.is_deleted.is_(False),
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.due_date < window_end,
        )
        .order_by(PaymentInstance.due_date)
        .all()
    )

    overdue_rows: list[dict[str, object]] = []
    upcoming_rows: list[dict[str, object]] = []
    for inst in instances:
        row = {
            "name": inst.template.name if inst.template else f"bill#{inst.bill_id}",
            "due_date": inst.due_date.isoformat(),
            "amount": inst.amount,
            "currency": inst.template.currency if inst.template else "PLN",
        }
        (overdue_rows if inst.due_date < today else upcoming_rows).append(row)

    lang = user.language_preference or "en"
    days = user.upcoming_digest_days
    title, body_text = build_upcoming_digest_text(
        days=days,
        overdue_rows=overdue_rows,
        upcoming_rows=upcoming_rows,
        language=lang,
    )

    def _send_email() -> None:
        smtp_host = settings.smtp_host
        if smtp_host is None:
            raise OSError("SMTP not configured")
        send_upcoming_digest_email(
            smtp_host=smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password=(
                settings.smtp_password.get_secret_value()
                if settings.smtp_password
                else None
            ),
            smtp_use_tls=settings.smtp_use_tls,
            from_addr=settings.reminder_from or settings.smtp_user or "",
            to_addr=user.email,
            days=days,
            overdue_rows=overdue_rows,
            upcoming_rows=upcoming_rows,
            language=lang,
        )

    result = notifications.deliver(
        title=title,
        body=body_text,
        notify_type="info",
        email_sender=_send_email,
    )
    if result.ok:
        logger.info(
            "Sent due digest to %s (user %s, %d overdue, %d upcoming) via %s",
            mask_email(user.email),
            user.id,
            len(overdue_rows),
            len(upcoming_rows),
            result.channel.value if result.channel else "unknown",
        )
    else:
        logger.warning(
            "Due digest delivery failed for %s (user %s)",
            mask_email(user.email),
            user.id,
        )
    return result.ok


def _send_due_digests(
    db: Session, *, now_utc: datetime, send_minute: int | None
) -> int:
    """Send digests whose local slot has arrived. Retries every scheduler tick.

    A user's slot is their chosen local weekday at (or after) their chosen
    local minute; `upcoming_digest_last_sent` keyed on the local date keeps it
    to one send per week. `send_minute` overrides "now" for tests.
    """
    sent = 0
    users = (
        db.query(User)
        .filter(
            User.is_active.is_(True),
            User.email_reminders_enabled.is_(True),
            User.upcoming_digest_enabled.is_(True),
        )
        .all()
    )
    for user in users:
        local_now = user_now(user.timezone, now_utc=now_utc)
        local_date = local_now.strftime("%Y-%m-%d")
        if local_now.weekday() != user.upcoming_digest_weekday:
            continue
        local_minute = (
            send_minute
            if send_minute is not None
            else local_now.hour * 60 + local_now.minute
        )
        if local_minute < user.upcoming_digest_minute:
            continue
        if user.upcoming_digest_last_sent == local_date:
            continue
        if send_upcoming_digest_for_user(db, user, now_utc):
            user.upcoming_digest_last_sent = local_date
            db.commit()
            sent += 1
    return sent


def send_daily_reminders(
    SessionLocal: sessionmaker, send_minute: int | None = None
) -> None:
    if not notifications.any_channel_configured():
        logger.warning("Reminder job: no notification channel configured, skipping")
        return

    now_utc = datetime.now(timezone.utc)
    logger.info("Reminder job started (UTC now=%s)", now_utc.isoformat())

    db: Session = SessionLocal()
    sent = 0
    try:
        users = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.email_reminders_enabled.is_(True),
                (
                    User.notify_1_day_before.is_(True)
                    | User.notify_2_days_before.is_(True)
                    | User.notify_on_day.is_(True)
                    | User.notify_1_day_after.is_(True)
                ),
            )
            .all()
        )

        # The send minute is local to each user's timezone (server-local when
        # unset), so matching happens in Python — offsets differ per user.
        for user in users:
            local_minute = (
                send_minute if send_minute is not None else _local_minute(user, now_utc)
            )
            if user.reminder_send_minute != local_minute:
                continue
            sent += send_reminders_for_user(db, user)

        # On each user's last local day of the month, send their monthly
        # summary regardless of reminder_send_minute — natural retry every
        # 30 min. Note: the query-then-flag pattern is not atomic; two
        # concurrent scheduler runs could both see last_sent=NULL and both
        # send. Acceptable at household scale given the 30-min cadence.
        summary_users = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.email_reminders_enabled.is_(True),
                User.monthly_summary_enabled.is_(True),
            )
            .all()
        )
        for u in summary_users:
            local_today = user_today(u.timezone, now_utc=now_utc)
            if (
                local_today.day
                != calendar.monthrange(local_today.year, local_today.month)[1]
            ):
                continue
            current_month = local_today.strftime("%Y-%m")
            if u.monthly_summary_last_sent == current_month:
                continue
            if send_monthly_summary_for_user(db, u, current_month):
                u.monthly_summary_last_sent = current_month
                db.commit()

        # Weekly due-overview digests whose local slot has arrived.
        sent += _send_due_digests(db, now_utc=now_utc, send_minute=send_minute)
    finally:
        db.close()

    logger.info("Reminder job finished: %d email(s) sent", sent)


def send_catchup_reminders(
    SessionLocal: sessionmaker, send_minute: int | None = None
) -> None:
    """Run on startup: send reminders for all users whose scheduled time has already passed today."""
    if not notifications.any_channel_configured():
        logger.warning(
            "Catch-up reminders: no notification channel configured, skipping"
        )
        return

    now_utc = datetime.now(timezone.utc)
    logger.info("Catch-up reminders started (UTC now=%s)", now_utc.isoformat())

    db: Session = SessionLocal()
    sent = 0
    try:
        users = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.email_reminders_enabled.is_(True),
                (
                    User.notify_1_day_before.is_(True)
                    | User.notify_2_days_before.is_(True)
                    | User.notify_on_day.is_(True)
                    | User.notify_1_day_after.is_(True)
                ),
            )
            .all()
        )
        # Each user's scheduled minute is local to their timezone
        # (server-local when unset); catch up everyone whose time has passed.
        for user in users:
            local_minute = (
                send_minute if send_minute is not None else _local_minute(user, now_utc)
            )
            if user.reminder_send_minute > local_minute:
                continue
            sent += send_reminders_for_user(db, user)

        # Also catch up missed monthly summaries on startup on each user's
        # last local day of the month.
        summary_users = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.email_reminders_enabled.is_(True),
                User.monthly_summary_enabled.is_(True),
            )
            .all()
        )
        for u in summary_users:
            local_today = user_today(u.timezone, now_utc=now_utc)
            if (
                local_today.day
                != calendar.monthrange(local_today.year, local_today.month)[1]
            ):
                continue
            current_month = local_today.strftime("%Y-%m")
            if u.monthly_summary_last_sent == current_month:
                continue
            if send_monthly_summary_for_user(db, u, current_month):
                u.monthly_summary_last_sent = current_month
                db.commit()

        # Weekly due-overview digests whose local slot has passed today.
        sent += _send_due_digests(db, now_utc=now_utc, send_minute=send_minute)
    finally:
        db.close()

    logger.info("Catch-up reminders finished: %d email(s) sent", sent)


def _send_and_flag(
    db: Session,
    user: User,
    instance: PaymentInstance,
    *,
    kind: str,
    flag_attr: str,
    language: str,
) -> bool:
    bill_name = (
        instance.template.name if instance.template else f"bill#{instance.bill_id}"
    )
    currency = instance.template.currency if instance.template else "PLN"

    title, body_text = build_reminder_text(
        bill_name=bill_name,
        due_date=instance.due_date,
        amount=instance.amount,
        currency=currency,
        kind=kind,
        language=language,
    )

    def _send_email() -> None:
        smtp_host = settings.smtp_host
        if smtp_host is None:
            raise OSError("SMTP not configured")
        send_reminder_email(
            smtp_host=smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password=(
                settings.smtp_password.get_secret_value()
                if settings.smtp_password
                else None
            ),
            smtp_use_tls=settings.smtp_use_tls,
            from_addr=settings.reminder_from or settings.smtp_user or "",
            to_addr=user.email,
            bill_name=bill_name,
            due_date=instance.due_date,
            amount=instance.amount,
            currency=currency,
            kind=kind,
            language=language,
        )

    result = notifications.deliver(
        title=title,
        body=body_text,
        notify_type="warning",
        email_sender=_send_email,
    )
    if not result.ok:
        logger.error(
            "Failed to send %s reminder to %s (user %s) for instance %s: %s",
            kind,
            mask_email(user.email),
            user.id,
            instance.id,
            result.error,
        )
        return False

    setattr(instance, flag_attr, True)
    if result.channel == NotificationChannel.email:
        instance.email_sent_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception as commit_exc:
        db.rollback()
        logger.critical(
            "Notification sent to %s (user %s) for instance %s but flag commit "
            "failed — duplicate send possible on next run: %s",
            mask_email(user.email),
            user.id,
            instance.id,
            commit_exc,
        )
        return False
    logger.info(
        "Sent %s reminder to %s (user %s) for '%s' (instance %s) via %s",
        kind,
        mask_email(user.email),
        user.id,
        bill_name,
        instance.id,
        result.channel.value if result.channel else "unknown",
    )
    return True
