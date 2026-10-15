import html
import smtplib
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from typing import Any

_SUBJECTS: dict[tuple[str, str], str] = {
    (
        "2_days_before",
        "en",
    ): "Reminder: {bill_name} due in 2 days ({amount} {currency})",
    (
        "2_days_before",
        "pl",
    ): "Przypomnienie: {bill_name} płatne za 2 dni ({amount} {currency})",
    (
        "2_days_before",
        "de",
    ): "Erinnerung: {bill_name} fällig in 2 Tagen ({amount} {currency})",
    ("upcoming", "en"): "Reminder: {bill_name} due tomorrow ({amount} {currency})",
    ("upcoming", "pl"): "Przypomnienie: {bill_name} płatne jutro ({amount} {currency})",
    ("upcoming", "de"): "Erinnerung: {bill_name} fällig morgen ({amount} {currency})",
    ("on_day", "en"): "Due today: {bill_name} ({amount} {currency})",
    ("on_day", "pl"): "Płatne dziś: {bill_name} ({amount} {currency})",
    ("on_day", "de"): "Heute fällig: {bill_name} ({amount} {currency})",
    (
        "1_day_after",
        "en",
    ): "Overdue: {bill_name} was due yesterday ({amount} {currency})",
    (
        "1_day_after",
        "pl",
    ): "Zaległość: {bill_name} było płatne wczoraj ({amount} {currency})",
    (
        "1_day_after",
        "de",
    ): "Überfällig: {bill_name} war gestern fällig ({amount} {currency})",
}

_BODIES: dict[tuple[str, str], str] = {
    ("2_days_before", "en"): (
        "This is a reminder that {bill_name} is due in 2 days ({due_date}).\n"
        "Amount: {amount} {currency}\n\n"
        "Manage your reminders in the Platybill app."
    ),
    ("2_days_before", "pl"): (
        "Przypominamy, że {bill_name} jest płatne za 2 dni ({due_date}).\n"
        "Kwota: {amount} {currency}\n\n"
        "Zarządzaj przypomnieniami w aplikacji Platybill."
    ),
    ("2_days_before", "de"): (
        "Erinnerung: {bill_name} ist in 2 Tagen fällig ({due_date}).\n"
        "Betrag: {amount} {currency}\n\n"
        "Verwalten Sie Ihre Erinnerungen in der Platybill App."
    ),
    ("upcoming", "en"): (
        "This is a reminder that {bill_name} is due tomorrow ({due_date}).\n"
        "Amount: {amount} {currency}\n\n"
        "Manage your reminders in the Platybill app."
    ),
    ("upcoming", "pl"): (
        "Przypominamy, że {bill_name} jest płatne jutro ({due_date}).\n"
        "Kwota: {amount} {currency}\n\n"
        "Zarządzaj przypomnieniami w aplikacji Platybill."
    ),
    ("upcoming", "de"): (
        "Erinnerung: {bill_name} ist morgen fällig ({due_date}).\n"
        "Betrag: {amount} {currency}\n\n"
        "Verwalten Sie Ihre Erinnerungen in der Platybill App."
    ),
    ("on_day", "en"): (
        "{bill_name} is due today ({due_date}).\n"
        "Amount: {amount} {currency}\n\n"
        "Manage your reminders in the Platybill app."
    ),
    ("on_day", "pl"): (
        "{bill_name} jest płatne dzisiaj ({due_date}).\n"
        "Kwota: {amount} {currency}\n\n"
        "Zarządzaj przypomnieniami w aplikacji Platybill."
    ),
    ("on_day", "de"): (
        "{bill_name} ist heute fällig ({due_date}).\n"
        "Betrag: {amount} {currency}\n\n"
        "Verwalten Sie Ihre Erinnerungen in der Platybill App."
    ),
    ("1_day_after", "en"): (
        "{bill_name} was due yesterday ({due_date}) and remains unpaid.\n"
        "Amount: {amount} {currency}\n\n"
        "Manage your reminders in the Platybill app."
    ),
    ("1_day_after", "pl"): (
        "{bill_name} było płatne wczoraj ({due_date}) i nadal nie zostało opłacone.\n"
        "Kwota: {amount} {currency}\n\n"
        "Zarządzaj przypomnieniami w aplikacji Platybill."
    ),
    ("1_day_after", "de"): (
        "{bill_name} war gestern fällig ({due_date}) und ist noch unbezahlt.\n"
        "Betrag: {amount} {currency}\n\n"
        "Verwalten Sie Ihre Erinnerungen in der Platybill App."
    ),
}


def build_reminder_text(
    *,
    bill_name: str,
    due_date: date,
    amount: Decimal,
    currency: str,
    kind: str,
    language: str,
) -> tuple[str, str]:
    """Return a localized (title, body) plain-text reminder."""
    lang = language if (kind, language) in _SUBJECTS else "en"
    ctx = {
        "bill_name": bill_name,
        "due_date": due_date.isoformat(),
        "amount": amount,
        "currency": currency,
    }
    return _SUBJECTS[(kind, lang)].format(**ctx), _BODIES[(kind, lang)].format(**ctx)


def send_reminder_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
    smtp_use_tls: bool = True,
    from_addr: str = "",
    to_addr: str,
    bill_name: str,
    due_date: date,
    amount: Decimal,
    currency: str,
    kind: str,
    language: str,
) -> None:
    lang = language if (kind, language) in _SUBJECTS else "en"
    ctx = {
        "bill_name": bill_name,
        "due_date": due_date.isoformat(),
        "amount": amount,
        "currency": currency,
    }

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = _SUBJECTS[(kind, lang)].format(**ctx)
    msg.set_content(_BODIES[(kind, lang)].format(**ctx))

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if smtp_use_tls:
            smtp.starttls()
        if smtp_user:
            smtp.login(smtp_user, smtp_password or "")
        smtp.send_message(msg)


_SUMMARY_SUBJECTS: dict[str, str] = {
    "en": "Monthly summary for {month_label} — Platybill",
    "pl": "Miesięczne podsumowanie za {month_label} — Platybill",
    "de": "Monatliche Zusammenfassung für {month_label} — Platybill",
}

_SUMMARY_HEADINGS: dict[str, dict[str, str]] = {
    "en": {
        "intro": "Here is your payment summary for {month_label}.",
        "paid_header": "Paid",
        "unpaid_header": "Unpaid / Overdue",
        "bill": "Bill",
        "due_date": "Due date",
        "expected": "Expected",
        "paid": "Paid",
        "paid_on": "Paid on",
        "amount": "Amount",
        "nothing_paid": "No payments were marked as paid this month.",
        "nothing_unpaid": "All bills are paid — great job!",
        "total_paid": "Total paid",
        "total_outstanding": "Total outstanding",
        "footer": "Manage your bills in the Platybill app.",
    },
    "pl": {
        "intro": "Oto podsumowanie płatności za {month_label}.",
        "paid_header": "Opłacone",
        "unpaid_header": "Nieopłacone / Zaległe",
        "bill": "Rachunek",
        "due_date": "Termin",
        "expected": "Kwota",
        "paid": "Zapłacono",
        "paid_on": "Data zapłaty",
        "amount": "Kwota",
        "nothing_paid": "Żadne płatności nie zostały oznaczone jako opłacone w tym miesiącu.",
        "nothing_unpaid": "Wszystkie rachunki są opłacone — świetna robota!",
        "total_paid": "Łącznie zapłacono",
        "total_outstanding": "Łącznie do zapłaty",
        "footer": "Zarządzaj rachunkami w aplikacji Platybill.",
    },
    "de": {
        "intro": "Hier ist Ihre Zahlungsübersicht für {month_label}.",
        "paid_header": "Bezahlt",
        "unpaid_header": "Unbezahlt / Überfällig",
        "bill": "Rechnung",
        "due_date": "Fälligkeitsdatum",
        "expected": "Erwartet",
        "paid": "Bezahlt",
        "paid_on": "Bezahlt am",
        "amount": "Betrag",
        "nothing_paid": "Keine Zahlungen wurden diesen Monat als bezahlt markiert.",
        "nothing_unpaid": "Alle Rechnungen sind bezahlt — gut gemacht!",
        "total_paid": "Gesamt bezahlt",
        "total_outstanding": "Gesamt ausstehend",
        "footer": "Verwalten Sie Ihre Rechnungen in der Platybill App.",
    },
}


def _build_summary_html(
    month_label: str,
    paid_rows: list[dict[str, Any]],
    unpaid_rows: list[dict[str, Any]],
    lang: str,
) -> str:
    h = _SUMMARY_HEADINGS.get(lang, _SUMMARY_HEADINGS["en"])

    def fmt_amount(amount: Any, currency: str) -> str:
        # Currency is user-controlled (template field); escape before embedding.
        return f"{Decimal(str(amount)):.2f} {html.escape(str(currency))}"

    # Paid section rows
    paid_html = ""
    for row in paid_rows:
        expected = fmt_amount(row["amount"], row["currency"])
        paid_actual = (
            fmt_amount(row["paid_amount"], row["currency"])
            if row.get("paid_amount")
            else expected
        )
        mismatch = row.get("paid_amount") and Decimal(
            str(row["paid_amount"])
        ) != Decimal(str(row["amount"]))
        paid_cell = paid_actual
        if mismatch:
            paid_cell = f'{paid_actual} <span style="color:#b45309">({h["expected"]}: {expected})</span>'
        paid_on = row.get("paid_at", "")
        if paid_on and hasattr(paid_on, "strftime"):
            paid_on = paid_on.strftime("%Y-%m-%d")
        elif paid_on and "T" in str(paid_on):
            paid_on = str(paid_on)[:10]
        paid_html += (
            f"<tr>"
            f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0">{html.escape(row["name"])}</td>'
            f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0">{html.escape(str(row["due_date"]))}</td>'
            f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0">{paid_cell}</td>'
            f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0">{html.escape(str(paid_on))}</td>'
            f"</tr>"
        )

    if not paid_html:
        paid_html = f'<tr><td colspan="4" style="padding:10px 12px;color:#64748b;font-style:italic">{h["nothing_paid"]}</td></tr>'

    # Unpaid section rows
    unpaid_html = ""
    for row in unpaid_rows:
        unpaid_html += (
            f"<tr>"
            f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0">{html.escape(row["name"])}</td>'
            f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0">{html.escape(str(row["due_date"]))}</td>'
            f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0">{fmt_amount(row["amount"], row["currency"])}</td>'
            f"</tr>"
        )

    if not unpaid_html:
        unpaid_html = f'<tr><td colspan="3" style="padding:10px 12px;color:#16a34a;font-style:italic">{h["nothing_unpaid"]}</td></tr>'

    # Totals
    total_paid = sum(
        Decimal(str(r.get("paid_amount") or r["amount"])) for r in paid_rows
    )
    total_outstanding = sum(Decimal(str(r["amount"])) for r in unpaid_rows)
    currencies = {r["currency"] for r in paid_rows + unpaid_rows}
    currency_label = html.escape(str(next(iter(currencies), "")))

    totals_html = (
        (
            f'<tr style="font-weight:bold;background:#f8fafc">'
            f'<td colspan="3" style="padding:8px 12px">{h["total_paid"]}</td>'
            f'<td style="padding:8px 12px">{total_paid:.2f} {currency_label}</td>'
            f"</tr>"
            f'<tr style="font-weight:bold;background:#f8fafc">'
            f'<td colspan="3" style="padding:8px 12px">{h["total_outstanding"]}</td>'
            f'<td style="padding:8px 12px">{total_outstanding:.2f} {currency_label}</td>'
            f"</tr>"
        )
        if paid_rows or unpaid_rows
        else ""
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;color:#1e293b;max-width:680px;margin:0 auto;padding:20px">
  <h2 style="color:#0f172a">{h["intro"].format(month_label=html.escape(month_label))}</h2>

  <h3 style="color:#15803d;margin-top:24px">✓ {h["paid_header"]}</h3>
  <table style="width:100%;border-collapse:collapse;font-size:14px">
    <thead>
      <tr style="background:#f1f5f9;text-align:left">
        <th style="padding:8px 12px">{h["bill"]}</th>
        <th style="padding:8px 12px">{h["due_date"]}</th>
        <th style="padding:8px 12px">{h["paid"]}</th>
        <th style="padding:8px 12px">{h["paid_on"]}</th>
      </tr>
    </thead>
    <tbody>{paid_html}</tbody>
  </table>

  <h3 style="color:#dc2626;margin-top:32px">⚠ {h["unpaid_header"]}</h3>
  <table style="width:100%;border-collapse:collapse;font-size:14px">
    <thead>
      <tr style="background:#f1f5f9;text-align:left">
        <th style="padding:8px 12px">{h["bill"]}</th>
        <th style="padding:8px 12px">{h["due_date"]}</th>
        <th style="padding:8px 12px">{h["amount"]}</th>
      </tr>
    </thead>
    <tbody>{unpaid_html}</tbody>
  </table>

  {f'<table style="width:100%;border-collapse:collapse;font-size:14px;margin-top:16px"><tbody>{totals_html}</tbody></table>' if totals_html else ''}

  <p style="margin-top:32px;color:#64748b;font-size:13px">{h["footer"]}</p>
</body>
</html>"""


def _build_summary_plaintext(
    month_label: str,
    paid_rows: list[dict[str, Any]],
    unpaid_rows: list[dict[str, Any]],
    lang: str,
) -> str:
    h = _SUMMARY_HEADINGS.get(lang, _SUMMARY_HEADINGS["en"])

    def fmt_amount(amount: Any, currency: str) -> str:
        return f"{Decimal(str(amount)):.2f} {currency}"

    lines = [h["intro"].format(month_label=month_label), ""]
    lines.append(f"=== {h['paid_header']} ===")
    if paid_rows:
        for row in paid_rows:
            expected = fmt_amount(row["amount"], row["currency"])
            paid_actual = (
                fmt_amount(row["paid_amount"], row["currency"])
                if row.get("paid_amount")
                else expected
            )
            mismatch = row.get("paid_amount") and Decimal(
                str(row["paid_amount"])
            ) != Decimal(str(row["amount"]))
            paid_on = row.get("paid_at", "")
            if paid_on and hasattr(paid_on, "strftime"):
                paid_on = paid_on.strftime("%Y-%m-%d")
            elif paid_on and "T" in str(paid_on):
                paid_on = str(paid_on)[:10]
            mismatch_note = f" ({h['expected']}: {expected})" if mismatch else ""
            lines.append(
                f"  {row['name']} | {row['due_date']} | {paid_actual}{mismatch_note} | {paid_on}"
            )
    else:
        lines.append(f"  {h['nothing_paid']}")

    lines += ["", f"=== {h['unpaid_header']} ==="]
    if unpaid_rows:
        for row in unpaid_rows:
            lines.append(
                f"  {row['name']} | {row['due_date']} | {fmt_amount(row['amount'], row['currency'])}"
            )
    else:
        lines.append(f"  {h['nothing_unpaid']}")

    if paid_rows or unpaid_rows:
        currencies = {r["currency"] for r in paid_rows + unpaid_rows}
        currency_label = next(iter(currencies), "")
        total_paid = sum(
            Decimal(str(r.get("paid_amount") or r["amount"])) for r in paid_rows
        )
        total_outstanding = sum(Decimal(str(r["amount"])) for r in unpaid_rows)
        lines += [
            "",
            f"{h['total_paid']}: {total_paid:.2f} {currency_label}",
            f"{h['total_outstanding']}: {total_outstanding:.2f} {currency_label}",
        ]

    lines += ["", h["footer"]]
    return "\n".join(lines)


def build_monthly_summary_text(
    *,
    month_label: str,
    paid_rows: list[dict[str, Any]],
    unpaid_rows: list[dict[str, Any]],
    language: str,
) -> tuple[str, str]:
    """Return a localized (title, body) compact plain-text monthly summary."""
    lang = language if language in _SUMMARY_SUBJECTS else "en"
    title = _SUMMARY_SUBJECTS[lang].format(month_label=month_label)
    body = _build_summary_plaintext(month_label, paid_rows, unpaid_rows, lang)
    return title, body


_RESET_SUBJECTS: dict[str, str] = {
    "en": "Reset your Platybill password",
    "pl": "Zresetuj hasło Platybill",
    "de": "Platybill Passwort zurücksetzen",
}

_RESET_BODIES: dict[str, str] = {
    "en": (
        "You requested a password reset for your Platybill account.\n\n"
        "Click the link below to set a new password (valid for {expires_label}):\n"
        "{reset_url}\n\n"
        "If you did not request this, you can ignore this email — your password will not change."
    ),
    "pl": (
        "Zostało złożone żądanie zresetowania hasła do konta Platybill.\n\n"
        "Kliknij poniższy link, aby ustawić nowe hasło (ważny przez {expires_label}):\n"
        "{reset_url}\n\n"
        "Jeśli nie prosiłeś o reset hasła, zignoruj tę wiadomość — Twoje hasło pozostanie bez zmian."
    ),
    "de": (
        "Sie haben eine Passwortzurücksetzung für Ihr Platybill-Konto angefordert.\n\n"
        "Klicken Sie auf den folgenden Link, um ein neues Passwort festzulegen (gültig für {expires_label}):\n"
        "{reset_url}\n\n"
        "Falls Sie diese Anforderung nicht gestellt haben, können Sie diese E-Mail ignorieren — Ihr Passwort bleibt unverändert."
    ),
}

_EXPIRES_LABELS: dict[str, str] = {
    "en": "{minutes} minutes",
    "pl": "{minutes} minut",
    "de": "{minutes} Minuten",
}


def send_password_reset_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
    smtp_use_tls: bool = True,
    from_addr: str = "",
    to_addr: str,
    reset_url: str,
    language: str,
    expires_minutes: int = 60,
) -> None:
    lang = language if language in _RESET_SUBJECTS else "en"

    if expires_minutes > 0:
        label_template = _EXPIRES_LABELS.get(lang, _EXPIRES_LABELS["en"])
        expires_label = label_template.format(minutes=expires_minutes)
    else:
        expires_label = "no expiry"

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = _RESET_SUBJECTS[lang]
    msg.set_content(
        _RESET_BODIES[lang].format(reset_url=reset_url, expires_label=expires_label)
    )

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if smtp_use_tls:
            smtp.starttls()
        if smtp_user:
            smtp.login(smtp_user, smtp_password or "")
        smtp.send_message(msg)


def send_monthly_summary_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
    smtp_use_tls: bool = True,
    from_addr: str = "",
    to_addr: str,
    month_label: str,
    paid_rows: list[dict[str, Any]],
    unpaid_rows: list[dict[str, Any]],
    language: str,
) -> None:
    lang = language if language in _SUMMARY_SUBJECTS else "en"
    subject = _SUMMARY_SUBJECTS[lang].format(month_label=month_label)
    plain = _build_summary_plaintext(month_label, paid_rows, unpaid_rows, lang)
    html = _build_summary_html(month_label, paid_rows, unpaid_rows, lang)

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if smtp_use_tls:
            smtp.starttls()
        if smtp_user:
            smtp.login(smtp_user, smtp_password or "")
        smtp.send_message(msg)


_DIGEST_SUBJECTS: dict[str, str] = {
    "en": "Due in the next {days} days — Platybill",
    "pl": "Terminy na najbliższe {days} dni — Platybill",
    "de": "Fällig in den nächsten {days} Tagen — Platybill",
}

_DIGEST_HEADINGS: dict[str, dict[str, str]] = {
    "en": {
        "intro": "Here is what is due over the next {days} days.",
        "overdue_header": "Overdue",
        "upcoming_header": "Due soon",
        "nothing": "Nothing is due — all clear!",
        "total": "Total due",
        "footer": "Manage your bills in the Platybill app.",
    },
    "pl": {
        "intro": "Oto co jest do zapłaty w ciągu najbliższych {days} dni.",
        "overdue_header": "Zaległe",
        "upcoming_header": "Wkrótce",
        "nothing": "Nic nie jest do zapłaty — wszystko na bieżąco!",
        "total": "Łącznie do zapłaty",
        "footer": "Zarządzaj rachunkami w aplikacji Platybill.",
    },
    "de": {
        "intro": "Das ist in den nächsten {days} Tagen fällig.",
        "overdue_header": "Überfällig",
        "upcoming_header": "Demnächst fällig",
        "nothing": "Nichts ist fällig — alles erledigt!",
        "total": "Gesamt fällig",
        "footer": "Verwalten Sie Ihre Rechnungen in der Platybill App.",
    },
}


def _digest_totals(rows: list[dict[str, Any]]) -> list[tuple[str, Decimal]]:
    """Per-currency totals for the digest body (handles mixed currencies)."""
    totals: dict[str, Decimal] = {}
    for row in rows:
        currency = str(row["currency"])
        totals[currency] = totals.get(currency, Decimal(0)) + Decimal(
            str(row["amount"])
        )
    return sorted(totals.items())


def _digest_row_text(row: dict[str, Any]) -> str:
    amount = Decimal(str(row["amount"]))
    return f"  {row['name']} | {row['due_date']} | {amount:.2f} {row['currency']}"


def _build_digest_plaintext(
    days: int,
    overdue_rows: list[dict[str, Any]],
    upcoming_rows: list[dict[str, Any]],
    lang: str,
) -> str:
    h = _DIGEST_HEADINGS.get(lang, _DIGEST_HEADINGS["en"])
    lines = [h["intro"].format(days=days), ""]
    if overdue_rows:
        lines.append(f"=== {h['overdue_header']} ===")
        lines.extend(_digest_row_text(row) for row in overdue_rows)
        lines.append("")
    lines.append(f"=== {h['upcoming_header']} ===")
    if upcoming_rows:
        lines.extend(_digest_row_text(row) for row in upcoming_rows)
    else:
        lines.append(f"  {h['nothing']}")
    totals = _digest_totals(overdue_rows + upcoming_rows)
    if totals:
        lines += [
            "",
            f"{h['total']}: "
            + " / ".join(f"{amount:.2f} {currency}" for currency, amount in totals),
        ]
    lines += ["", h["footer"]]
    return "\n".join(lines)


def _build_digest_html(
    days: int,
    overdue_rows: list[dict[str, Any]],
    upcoming_rows: list[dict[str, Any]],
    lang: str,
) -> str:
    h = _DIGEST_HEADINGS.get(lang, _DIGEST_HEADINGS["en"])
    cell = 'style="padding:6px 12px;border-bottom:1px solid #e2e8f0"'

    def row_html(row: dict[str, Any], color: str) -> str:
        amount = (
            f"{Decimal(str(row['amount'])):.2f} {html.escape(str(row['currency']))}"
        )
        return (
            f"<tr>"
            f"<td {cell}>{html.escape(row['name'])}</td>"
            f"<td {cell}>{html.escape(str(row['due_date']))}</td>"
            f'<td {cell} style="padding:6px 12px;border-bottom:1px solid #e2e8f0;color:{color}">{amount}</td>'
            f"</tr>"
        )

    sections = [f"<p>{html.escape(h['intro'].format(days=days))}</p>"]
    if overdue_rows:
        sections.append(f'<h3 style="margin:18px 0 6px">{h["overdue_header"]}</h3>')
        sections.append("<table style='border-collapse:collapse;width:100%'>")
        sections.extend(row_html(row, "#dc2626") for row in overdue_rows)
        sections.append("</table>")
    sections.append(f'<h3 style="margin:18px 0 6px">{h["upcoming_header"]}</h3>')
    sections.append("<table style='border-collapse:collapse;width:100%'>")
    if upcoming_rows:
        sections.extend(row_html(row, "#0f172a") for row in upcoming_rows)
    else:
        sections.append(
            f'<tr><td colspan="3" style="padding:10px 12px;color:#16a34a;'
            f'font-style:italic">{h["nothing"]}</td></tr>'
        )
    sections.append("</table>")
    totals = _digest_totals(overdue_rows + upcoming_rows)
    if totals:
        totals_label = " / ".join(
            f"{amount:.2f} {html.escape(currency)}" for currency, amount in totals
        )
        sections.append(
            f'<p style="margin-top:14px;font-weight:bold">{h["total"]}: {totals_label}</p>'
        )
    sections.append(f'<p style="color:#64748b;font-size:12px">{h["footer"]}</p>')
    return "".join(sections)


def build_upcoming_digest_text(
    *,
    days: int,
    overdue_rows: list[dict[str, Any]],
    upcoming_rows: list[dict[str, Any]],
    language: str,
) -> tuple[str, str]:
    """Return a localized (title, body) compact plain-text dues digest."""
    lang = language if language in _DIGEST_SUBJECTS else "en"
    title = _DIGEST_SUBJECTS[lang].format(days=days)
    body = _build_digest_plaintext(days, overdue_rows, upcoming_rows, lang)
    return title, body


def send_upcoming_digest_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
    smtp_use_tls: bool = True,
    from_addr: str = "",
    to_addr: str,
    days: int,
    overdue_rows: list[dict[str, Any]],
    upcoming_rows: list[dict[str, Any]],
    language: str,
) -> None:
    lang = language if language in _DIGEST_SUBJECTS else "en"
    subject = _DIGEST_SUBJECTS[lang].format(days=days)
    plain = _build_digest_plaintext(days, overdue_rows, upcoming_rows, lang)
    html_body = _build_digest_html(days, overdue_rows, upcoming_rows, lang)

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if smtp_use_tls:
            smtp.starttls()
        if smtp_user:
            smtp.login(smtp_user, smtp_password or "")
        smtp.send_message(msg)


_TEST_SUBJECTS: dict[str, str] = {
    "en": "Platybill test notification",
    "pl": "Powiadomienie testowe Platybill",
    "de": "Platybill Testbenachrichtigung",
}

_TEST_BODIES: dict[str, str] = {
    "en": (
        "This is a test notification from Platybill. "
        "If you received it, email notifications are working."
    ),
    "pl": (
        "To jest powiadomienie testowe z Platybill. "
        "Jeśli je otrzymałeś, powiadomienia e-mail działają."
    ),
    "de": (
        "Dies ist eine Testbenachrichtigung von Platybill. "
        "Wenn Sie sie erhalten haben, funktionieren die E-Mail-Benachrichtigungen."
    ),
}


def send_test_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
    smtp_use_tls: bool = True,
    from_addr: str = "",
    to_addr: str,
    language: str = "en",
) -> None:
    lang = language if language in _TEST_SUBJECTS else "en"
    plain = _TEST_BODIES[lang]
    html_body = (
        "<html><body>"
        f'<p style="font-family:Arial,sans-serif;color:#1e293b">{html.escape(plain)}</p>'
        "</body></html>"
    )

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = _TEST_SUBJECTS[lang]
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        if smtp_use_tls:
            smtp.starttls()
        if smtp_user:
            smtp.login(smtp_user, smtp_password or "")
        smtp.send_message(msg)
