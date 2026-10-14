import calendar
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.config import settings
from app.core.logging_utils import mask_email
from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.models.user import User
from app.services import notifications
from app.services.email import (
    build_monthly_summary_text,
    build_reminder_text,
    send_monthly_summary_email,
    send_reminder_email,
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


def send_reminders_for_user(db: Session, user: User) -> int:
    """Send due reminders for a single user. Returns count of emails sent."""
    if _is_blocked_domain(user.email):
        logger.debug(
            "Skipping reminders for blocked domain: %s (user %s)",
            mask_email(user.email),
            user.id,
        )
        return 0
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
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


def send_daily_reminders(
    SessionLocal: sessionmaker, send_minute: int | None = None
) -> None:
    if not notifications.any_channel_configured():
        logger.warning("Reminder job: no notification channel configured, skipping")
        return

    now_utc = datetime.now(timezone.utc)
    current_minute = (
        send_minute if send_minute is not None else now_utc.hour * 60 + now_utc.minute
    )
    today = now_utc.date()
    logger.info("Reminder job started (today=%s UTC, minute=%d)", today, current_minute)

    db: Session = SessionLocal()
    sent = 0
    try:
        users = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.email_reminders_enabled.is_(True),
                User.reminder_send_minute == current_minute,
                (
                    User.notify_1_day_before.is_(True)
                    | User.notify_2_days_before.is_(True)
                    | User.notify_on_day.is_(True)
                    | User.notify_1_day_after.is_(True)
                ),
            )
            .all()
        )

        for user in users:
            sent += send_reminders_for_user(db, user)

        # On the last day of the month, send monthly summaries to all eligible
        # users regardless of reminder_send_minute — natural retry every 30 min.
        # Note: the query-then-flag pattern is not atomic; two concurrent scheduler
        # runs could both see last_sent=NULL and both send. Acceptable at household
        # scale given the 30-min cadence makes overlap unlikely.
        is_last_day = today.day == calendar.monthrange(today.year, today.month)[1]
        if is_last_day:
            current_month = today.strftime("%Y-%m")
            summary_users = (
                db.query(User)
                .filter(
                    User.is_active.is_(True),
                    User.email_reminders_enabled.is_(True),
                    User.monthly_summary_enabled.is_(True),
                    (User.monthly_summary_last_sent.is_(None))
                    | (User.monthly_summary_last_sent != current_month),
                )
                .all()
            )
            for u in summary_users:
                if send_monthly_summary_for_user(db, u, current_month):
                    u.monthly_summary_last_sent = current_month
                    db.commit()
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
    current_minute = (
        send_minute if send_minute is not None else now_utc.hour * 60 + now_utc.minute
    )
    today = now_utc.date()
    logger.info(
        "Catch-up reminders started (today=%s UTC, up to minute=%d)",
        today,
        current_minute,
    )

    db: Session = SessionLocal()
    sent = 0
    try:
        users = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.email_reminders_enabled.is_(True),
                User.reminder_send_minute <= current_minute,
                (
                    User.notify_1_day_before.is_(True)
                    | User.notify_2_days_before.is_(True)
                    | User.notify_on_day.is_(True)
                    | User.notify_1_day_after.is_(True)
                ),
            )
            .all()
        )
        for user in users:
            sent += send_reminders_for_user(db, user)

        # Also catch up missed monthly summaries on startup if today is last day.
        is_last_day = today.day == calendar.monthrange(today.year, today.month)[1]
        if is_last_day:
            current_month = today.strftime("%Y-%m")
            summary_users = (
                db.query(User)
                .filter(
                    User.is_active.is_(True),
                    User.email_reminders_enabled.is_(True),
                    User.monthly_summary_enabled.is_(True),
                    (User.monthly_summary_last_sent.is_(None))
                    | (User.monthly_summary_last_sent != current_month),
                )
                .all()
            )
            for u in summary_users:
                if send_monthly_summary_for_user(db, u, current_month):
                    u.monthly_summary_last_sent = current_month
                    db.commit()
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
