from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser
import html
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InstallmentDetail:
    index: int
    amount: Decimal
    due_date: date
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "amount": float(self.amount),
            "due_date": self.due_date.isoformat(),
            "status": self.status,
        }


@dataclass
class ExtractedBnpl:
    merchant: str
    order_id: str
    total_amount: Decimal
    installment_amount: Decimal
    currency: str
    start_date: date
    interval_count: int
    max_occurrences: int
    installments: list[InstallmentDetail]
    type: str = "afterpay"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.type,
            "merchant": self.merchant,
            "order_id": self.order_id,
            "total_amount": float(self.total_amount),
            "installment_amount": float(self.installment_amount),
            "currency": self.currency,
            "start_date": self.start_date.isoformat(),
            "interval_count": self.interval_count,
            "max_occurrences": self.max_occurrences,
            "installments": [i.to_dict() for i in self.installments],
        }
        if self.warnings:
            result["warnings"] = list(self.warnings)
        return result


class _AutomationIdParser(HTMLParser):
    """HTML parser extracting text from elements with automation_id attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.current_id: str | None = None
        self.data: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for k, v in attrs:
            if k == "automation_id" and v:
                self.current_id = v
                self.data.setdefault(v, "")

    def handle_endtag(self, tag: str) -> None:
        self.current_id = None

    def handle_data(self, data: str) -> None:
        if self.current_id:
            self.data[self.current_id] += data


def is_afterpay_email(from_addr: str, subject: str, body: str = "") -> bool:
    """Check if an email message originated from Afterpay / Clearpay."""
    from_lower = from_addr.lower()
    subject_lower = subject.lower()
    body_lower = body.lower()

    if "afterpay" in from_lower or "clearpay" in from_lower:
        return True
    if "afterpay" in subject_lower:
        return True
    if (
        "afterpay order" in body_lower
        or "thank you for choosing afterpay" in body_lower
    ):
        return True
    return False


def _parse_amount(text: str) -> Decimal | None:
    """Extract numeric amount from string like '$71.50' or 'Total  $286.00'."""
    clean = re.sub(r"[^\d.]", "", text)
    if not clean:
        return None
    try:
        val = Decimal(clean)
        return val if val > 0 else None
    except InvalidOperation:
        return None


def _parse_date(text: str) -> date | None:
    """Parse date from formats like 'Sun, 01/11/2026', '01/11/2026', '2026-11-01'."""
    # Look for DD/MM/YYYY
    match_dmy = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match_dmy:
        d, m, y = map(int, match_dmy.groups())
        try:
            return date(y, m, d)
        except ValueError:
            pass

    # Look for YYYY-MM-DD
    match_iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match_iso:
        y, m, d = map(int, match_iso.groups())
        try:
            return date(y, m, d)
        except ValueError:
            pass

    return None


def parse_afterpay(
    html_body: str,
    text_body: str = "",
    *,
    reference_date: date | None = None,
) -> ExtractedBnpl | None:
    """Extract Afterpay installment plan from HTML or plain-text body."""
    if html_body:
        extracted = _parse_from_html(html_body, reference_date=reference_date)
        if extracted is not None:
            return extracted

    if text_body:
        return _parse_from_text(text_body, reference_date=reference_date)

    return None


def _parse_from_html(
    html_content: str, *, reference_date: date | None = None
) -> ExtractedBnpl | None:
    parser = _AutomationIdParser()
    try:
        parser.feed(html_content)
    except Exception as exc:
        logger.debug("HTMLParser error on email body: %s", exc)

    data = {k: html.unescape(v).strip() for k, v in parser.data.items()}

    # 1. Retailer / Merchant
    merchant = data.get("email-retailer")
    if not merchant:
        # Fallback regex in HTML text
        match = re.search(
            r"Your order with <strong>([^<]+)</strong> is confirmed",
            html_content,
            re.IGNORECASE,
        )
        if match:
            merchant = html.unescape(match.group(1)).strip()

    if not merchant:
        return None

    # Clean merchant name (e.g. remove trailing 'Pty Limited', 'Pty Ltd' if desired, or keep as is)
    merchant = re.sub(r"\s+", " ", merchant).strip()

    # 2. Order number
    order_id = data.get("email-ordernumber")
    if not order_id:
        match = re.search(
            r"Afterpay order number:[^<]*?<[^>]+>([^<]+)</",
            html_content,
            re.IGNORECASE,
        )
        if match:
            order_id = html.unescape(match.group(1)).strip()

    if not order_id:
        # Fallback regex anywhere in text
        match = re.search(r"order number[:\s]+(\d+)", html_content, re.IGNORECASE)
        order_id = match.group(1) if match else "UNKNOWN"

    # 3. Installments
    installments: list[InstallmentDetail] = []
    warnings: list[str] = []
    for i in range(1, 10):
        amount_str = data.get(f"email-payment{i}-amount")
        date_str = data.get(f"email-payment{i}-date")
        status_str = data.get(f"email-payment{i}-status")
        if not amount_str or not date_str:
            break

        amt = _parse_amount(amount_str)
        dt = _parse_date(date_str)
        if dt is not None:
            dt, warn = reconcile_date_weekday(
                dt, date_str, reference_date=reference_date
            )
            if warn:
                warnings.append(warn)
        if amt is not None and dt is not None:
            installments.append(
                InstallmentDetail(
                    index=i,
                    amount=amt,
                    due_date=dt,
                    status=status_str if status_str else None,
                )
            )

    if not installments:
        return None

    # Total amount
    total_str = data.get("email-order-total", "")
    total_amount = _parse_amount(total_str) or sum(
        (i.amount for i in installments), Decimal("0")
    )

    # Cadence
    interval_count = 2  # default fortnightly
    if len(installments) >= 2:
        diff_days = (installments[1].due_date - installments[0].due_date).days
        if 6 <= diff_days <= 8:
            interval_count = 1  # weekly
        elif 12 <= diff_days <= 16:
            interval_count = 2  # fortnightly

    return ExtractedBnpl(
        merchant=merchant,
        order_id=order_id,
        total_amount=total_amount,
        installment_amount=installments[0].amount,
        currency="AUD",  # default AUD for AU Afterpay, or detect from symbol
        start_date=installments[0].due_date,
        interval_count=interval_count,
        max_occurrences=len(installments),
        installments=installments,
        type="afterpay",
        warnings=warnings,
    )


def _parse_from_text(
    text: str, *, reference_date: date | None = None
) -> ExtractedBnpl | None:
    """Fallback parser for plain-text emails."""
    merchant_match = re.search(
        r"(?:Your order with|Retailer:)\s*([^\n\r]+?)(?:\s*is confirmed|\s*Afterpay|\n|$)",
        text,
        re.IGNORECASE,
    )
    if not merchant_match:
        return None
    merchant = merchant_match.group(1).strip()

    order_match = re.search(
        r"Afterpay order number:\s*([A-Za-z0-9]+)", text, re.IGNORECASE
    )
    order_id = order_match.group(1).strip() if order_match else "UNKNOWN"

    # Search for payments
    installments: list[InstallmentDetail] = []
    warnings: list[str] = []
    payment_blocks = re.findall(
        r"(FIRST|SECOND|THIRD|FOURTH|\d+(?:st|nd|rd|th))\s+PAYMENT[\s\S]*?\$?(\d+\.\d{2})[\s\S]*?DUE DATE:\s*([A-Za-z]+,\s*\d{1,2}/\d{1,2}/\d{4}|\d{1,2}/\d{1,2}/\d{4})",
        text,
        re.IGNORECASE,
    )

    for idx, (_, amount_str, date_str) in enumerate(payment_blocks, start=1):
        amt = _parse_amount(amount_str)
        dt = _parse_date(date_str)
        if dt is not None:
            dt, warn = reconcile_date_weekday(
                dt, date_str, reference_date=reference_date
            )
            if warn:
                warnings.append(warn)
        if amt and dt:
            installments.append(
                InstallmentDetail(index=idx, amount=amt, due_date=dt, status=None)
            )

    if not installments:
        return None

    interval_count = 2
    if len(installments) >= 2:
        diff_days = (installments[1].due_date - installments[0].due_date).days
        if 6 <= diff_days <= 8:
            interval_count = 1
        elif 12 <= diff_days <= 16:
            interval_count = 2

    total_match = re.search(r"Total\s*\$?(\d+\.\d{2})", text, re.IGNORECASE)
    total_amount = (
        Decimal(total_match.group(1))
        if total_match
        else sum((i.amount for i in installments), Decimal("0"))
    )

    return ExtractedBnpl(
        merchant=merchant,
        order_id=order_id,
        total_amount=total_amount,
        installment_amount=installments[0].amount,
        currency="AUD",
        start_date=installments[0].due_date,
        interval_count=interval_count,
        max_occurrences=len(installments),
        installments=installments,
        type="afterpay",
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Screenshot / BNPL instalment list parsing (Afterpay "Your orders" view)
# ---------------------------------------------------------------------------

_MONTH_NAMES: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_WEEKDAY_NAMES: dict[str, int] = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "weds": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

_WD_TOKEN = (
    r"\b("
    r"Mon(?:day)?|Tue(?:s(?:day)?)?|Wed(?:s|nesday)?|"
    r"Thu(?:r(?:s(?:day)?)?)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?"
    r")\b"
)
_WD_TOKEN_RE = re.compile(_WD_TOKEN, re.IGNORECASE)
_WD_DM_RE = re.compile(
    _WD_TOKEN + r"\.?,?\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})(?:,?\s+\d{4})?\b",
    re.IGNORECASE,
)
_WD_MD_RE = re.compile(
    _WD_TOKEN + r"\.?,?\s+([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b",
    re.IGNORECASE,
)
_WD_DMY_SLASH_RE = re.compile(
    _WD_TOKEN + r"\.?,?\s+(\d{1,2})/(\d{1,2})(?:/\d{4})?\b",
    re.IGNORECASE,
)
_WD_ISO_RE = re.compile(
    _WD_TOKEN + r"\.?,?\s+\d{4}-(\d{1,2})-(\d{1,2})\b",
    re.IGNORECASE,
)


def _find_weekday_mentions(
    source_text: str, month: int, day: int
) -> list[tuple[int, str]]:
    """Find (weekday_index, raw_label) pairs in source_text matching (month, day)."""
    matches: list[tuple[int, str]] = []
    for m in _WD_DM_RE.finditer(source_text):
        wd = _WEEKDAY_NAMES.get(m.group(1).lower())
        m_month = _MONTH_NAMES.get(m.group(3).lower())
        if wd is not None and m_month == month and int(m.group(2)) == day:
            matches.append((wd, m.group(1)))
    for m in _WD_MD_RE.finditer(source_text):
        wd = _WEEKDAY_NAMES.get(m.group(1).lower())
        m_month = _MONTH_NAMES.get(m.group(2).lower())
        if wd is not None and m_month == month and int(m.group(3)) == day:
            matches.append((wd, m.group(1)))
    for m in _WD_DMY_SLASH_RE.finditer(source_text):
        wd = _WEEKDAY_NAMES.get(m.group(1).lower())
        if wd is not None and int(m.group(3)) == month and int(m.group(2)) == day:
            matches.append((wd, m.group(1)))
    for m in _WD_ISO_RE.finditer(source_text):
        wd = _WEEKDAY_NAMES.get(m.group(1).lower())
        if wd is not None and int(m.group(2)) == month and int(m.group(3)) == day:
            matches.append((wd, m.group(1)))
    return matches


def reconcile_date_weekday(
    parsed: date | None,
    source_text: str | None,
    *,
    reference_date: date | None = None,
) -> tuple[date | None, str | None]:
    """Reconcile a parsed date against any weekday printed with it in source_text.

    When source_text includes a weekday for the same (month, day) — e.g.
    'Sun, 27 Dec' — and `parsed` falls on a different weekday, try `ref.year`
    then `ref.year + 1` and pick the year whose weekday matches. If neither
    matches, leave `parsed` unchanged and return a warning string (also logged).
    """
    if parsed is None or not source_text:
        return parsed, None

    mentions = _find_weekday_mentions(source_text, parsed.month, parsed.day)
    if not mentions:
        return parsed, None

    if any(wd == parsed.weekday() for wd, _ in mentions):
        return parsed, None

    expected_wd, wd_label = mentions[0]
    ref = reference_date or date.today()
    for year in (ref.year, ref.year + 1):
        try:
            candidate = date(year, parsed.month, parsed.day)
        except ValueError:
            continue
        if candidate.weekday() == expected_wd:
            logger.info(
                "Reconciled due_date year %s -> %s to match source weekday '%s'",
                parsed.isoformat(),
                candidate.isoformat(),
                wd_label,
            )
            return candidate, None

    warning = (
        f"Parsed date {parsed.isoformat()} ({parsed.strftime('%a')}) does not "
        f"match source weekday '{wd_label}' and could not be reconciled in "
        f"{ref.year}-{ref.year + 1}"
    )
    logger.warning("%s", warning)
    return parsed, warning


_WEEKDAY_PREFIX = r"(?:\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?"
_DMY_MONTH_YEAR_RE = re.compile(
    _WEEKDAY_PREFIX + r"\b(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
_MDY_MONTH_YEAR_RE = re.compile(
    _WEEKDAY_PREFIX + r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
_DM_NO_YEAR_RE = re.compile(
    _WEEKDAY_PREFIX + r"\b(\d{1,2})\s+([A-Za-z]{3,9})\b",
    re.IGNORECASE,
)
_MD_NO_YEAR_RE = re.compile(
    _WEEKDAY_PREFIX + r"\b([A-Za-z]{3,9})\s+(\d{1,2})\b",
    re.IGNORECASE,
)

_COUNTER_RE = re.compile(r"\b(\d{1,2})\s*(?:of|/)\s*(\d{1,2})\b", re.IGNORECASE)
_ANCHOR_LINE_RE = re.compile(
    r"^\s*(\d{1,2})\s+of\s+(\d{1,2})\s*(?:[•·\-|•]|\s)\s*(.+?)\s*$",
    re.IGNORECASE,
)
_INLINE_AMOUNT_RE = re.compile(
    r"(?:\bPay\s+)?\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})\b",
    re.IGNORECASE,
)
_STANDALONE_AMOUNT_RE = re.compile(
    r"^\s*(?:Pay\s+)?\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})\s*$",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}(?:\s*[AP]M)?$", re.IGNORECASE)
_DUE_IN_DAYS_RE = re.compile(r"^due\s+in\s+\d+\s+days?$", re.IGNORECASE)
_NOISE_PHRASES: frozenset[str] = frozenset(
    {
        "your orders",
        "total you owe",
        "upcoming payments",
        "active orders",
        "history",
        "make multiple payments",
        "logo",
        "multiple orders",
    }
)


@dataclass(frozen=True)
class BnplInstallmentRow:
    """One instalment extracted from an Afterpay / BNPL list screenshot."""

    merchant: str
    amount: Decimal
    due_date: date
    installment_number: int
    total_installments: int
    currency: str = "AUD"
    warnings: tuple[str, ...] = ()

    @property
    def installment_label(self) -> str:
        return f"{self.installment_number} of {self.total_installments}"

    @property
    def remaining_installments(self) -> int:
        return max(0, self.total_installments - self.installment_number)

    def to_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "type": "afterpay",
            "source_kind": "bnpl_list",
            "merchant": self.merchant,
            "installment_number": self.installment_number,
            "total_installments": self.total_installments,
            "installment_label": self.installment_label,
            "remaining_installments": self.remaining_installments,
            "interval_count": 2,
            "max_occurrences": self.total_installments,
        }
        if self.warnings:
            meta["warnings"] = list(self.warnings)
        return meta


def _clean_merchant(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"^afterpay\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    return text


def _is_noise_merchant(value: str) -> bool:
    low = value.strip().lower()
    if not low or low in _NOISE_PHRASES:
        return True
    if _DUE_IN_DAYS_RE.match(low) or _CLOCK_RE.match(low):
        return True
    return False


def _parse_bnpl_amount(value: Any) -> Decimal | None:
    """Parse an AUD instalment amount from numeric or string form (e.g. 'Pay $28.50')."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            return None
    elif isinstance(value, str):
        match = _INLINE_AMOUNT_RE.search(value)
        raw = match.group(1) if match else re.sub(r"[^\d.,]", "", value)
        raw = raw.replace(",", "")
        if not raw:
            return None
        try:
            dec = Decimal(raw)
        except InvalidOperation:
            return None
    else:
        return None

    if dec <= 0:
        return None
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_installment_counter(
    label: Any = None,
    number: Any = None,
    total: Any = None,
    fallback_text: str | None = None,
) -> tuple[int, int] | None:
    """Extract and validate an (n, m) instalment counter where 1 <= n <= m, m >= 2."""
    if (
        number is not None
        and total is not None
        and not isinstance(number, bool)
        and not isinstance(total, bool)
    ):
        try:
            n = int(number)
            m = int(total)
            if 1 <= n <= m and m >= 2:
                return (n, m)
        except (ValueError, TypeError):
            pass

    for candidate in (label, fallback_text):
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        match = _COUNTER_RE.search(candidate)
        if match:
            n, m = int(match.group(1)), int(match.group(2))
            if 1 <= n <= m and m >= 2:
                return (n, m)
    return None


def _extract_explicit_year_month(text: str) -> tuple[int, int] | None:
    """Return (year, month) when `text` contains an explicit 4-digit year."""
    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        y, m = int(iso.group(1)), int(iso.group(2))
        if 1 <= m <= 12:
            return (y, m)
    dmy = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if dmy:
        m, y = int(dmy.group(2)), int(dmy.group(3))
        if 1 <= m <= 12:
            return (y, m)
    for regex, month_group, year_group in (
        (_DMY_MONTH_YEAR_RE, 2, 3),
        (_MDY_MONTH_YEAR_RE, 1, 3),
    ):
        match = regex.search(text)
        if match:
            month = _MONTH_NAMES.get(match.group(month_group).lower())
            if month is not None:
                return (int(match.group(year_group)), month)
    return None


def _resolve_yearless_date(
    month: int,
    day: int,
    *,
    reference_date: date | None = None,
    explicit_year_hint: tuple[int, int] | None = None,
) -> date | None:
    if explicit_year_hint is not None:
        hint_year, hint_month = explicit_year_hint
        if hint_month <= 3 and month >= 10:
            year = hint_year - 1
        elif hint_month >= 10 and month <= 3:
            year = hint_year + 1
        else:
            year = hint_year
        try:
            return date(year, month, day)
        except ValueError:
            return None

    ref = reference_date or date.today()
    candidate: date | None = None
    for y in (ref.year, ref.year + 1, ref.year - 1):
        try:
            candidate = date(y, month, day)
            break
        except ValueError:
            continue
    if candidate is None:
        return None

    if candidate < ref - timedelta(days=60):
        try:
            return date(candidate.year + 1, month, day)
        except ValueError:
            return candidate
    if candidate > ref + timedelta(days=300):
        try:
            return date(candidate.year - 1, month, day)
        except ValueError:
            return candidate
    return candidate


def _parse_bnpl_date_checked(
    text: str,
    *,
    reference_date: date | None = None,
    explicit_year_hint: tuple[int, int] | None = None,
) -> tuple[date | None, str | None]:
    """Parse an Afterpay date string and reconcile any weekday mismatch."""
    if not text or not text.strip():
        return None, None

    # Strip any leading "n of m •" counter prefix if embedded.
    cleaned = re.sub(
        r"^\s*\d{1,2}\s*(?:of|/)\s*\d{1,2}\s*[•·\-|]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    parsed: date | None = None

    # 1. Explicit numeric dates (YYYY-MM-DD, DD/MM/YYYY)
    numeric = _parse_date(cleaned)
    if numeric is not None:
        parsed = numeric

    # 2. Explicit month-name dates with year ('3 Jan, 2027', 'Jan 3, 2027')
    if parsed is None:
        m_dmy = _DMY_MONTH_YEAR_RE.search(cleaned)
        if m_dmy:
            day = int(m_dmy.group(1))
            month = _MONTH_NAMES.get(m_dmy.group(2).lower())
            year = int(m_dmy.group(3))
            if month is not None:
                try:
                    parsed = date(year, month, day)
                except ValueError:
                    return None, None

    if parsed is None:
        m_mdy = _MDY_MONTH_YEAR_RE.search(cleaned)
        if m_mdy:
            month = _MONTH_NAMES.get(m_mdy.group(1).lower())
            day = int(m_mdy.group(2))
            year = int(m_mdy.group(3))
            if month is not None:
                try:
                    parsed = date(year, month, day)
                except ValueError:
                    return None, None

    # 3. Yearless month-name dates ('Sun, 27 Dec', '27 Dec', 'Sun, Dec 27')
    if parsed is None:
        m_dm = _DM_NO_YEAR_RE.search(cleaned)
        if m_dm:
            day = int(m_dm.group(1))
            month = _MONTH_NAMES.get(m_dm.group(2).lower())
            if month is not None:
                parsed = _resolve_yearless_date(
                    month,
                    day,
                    reference_date=reference_date,
                    explicit_year_hint=explicit_year_hint,
                )

    if parsed is None:
        m_md = _MD_NO_YEAR_RE.search(cleaned)
        if m_md:
            month = _MONTH_NAMES.get(m_md.group(1).lower())
            day = int(m_md.group(2))
            if month is not None:
                parsed = _resolve_yearless_date(
                    month,
                    day,
                    reference_date=reference_date,
                    explicit_year_hint=explicit_year_hint,
                )

    if parsed is None:
        return None, None
    return reconcile_date_weekday(parsed, cleaned, reference_date=reference_date)


def parse_bnpl_date(
    text: str,
    *,
    reference_date: date | None = None,
    explicit_year_hint: tuple[int, int] | None = None,
) -> date | None:
    """Parse Afterpay screenshot date strings such as 'Sun, 27 Dec' or '3 Jan, 2027'."""
    parsed, _ = _parse_bnpl_date_checked(
        text,
        reference_date=reference_date,
        explicit_year_hint=explicit_year_hint,
    )
    return parsed


def parse_afterpay_installments_payload(
    payload: dict[str, Any],
    *,
    reference_date: date | None = None,
    raw_text: str | None = None,
) -> list[BnplInstallmentRow]:
    """Validate and normalize a vision-LLM JSON payload containing BNPL instalments.

    Returns an empty list when the payload does not represent a BNPL instalment
    list (e.g. an ordinary single bill or rows without an 'n of m' counter).
    """
    raw_items = payload.get("installments")
    if not isinstance(raw_items, list) or not raw_items:
        return []

    explicit_hint: tuple[int, int] | None = None
    for item in raw_items:
        if isinstance(item, dict):
            raw_hint = str(item.get("due_date") or "")
            if _WD_TOKEN_RE.search(raw_hint):
                continue
            hint = _extract_explicit_year_month(raw_hint)
            if hint is not None:
                explicit_hint = hint
                break

    rows: list[BnplInstallmentRow] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        merchant = _clean_merchant(str(item.get("merchant") or ""))
        if _is_noise_merchant(merchant):
            continue
        amount = _parse_bnpl_amount(item.get("amount"))
        if amount is None:
            continue
        raw_due = str(item.get("due_date") or "")
        counter = _parse_installment_counter(
            label=item.get("installment_label") or item.get("counter"),
            number=item.get("installment_number"),
            total=item.get("total_installments"),
            fallback_text=raw_due,
        )
        if counter is None:
            continue
        due, warning = _parse_bnpl_date_checked(
            raw_due,
            reference_date=reference_date,
            explicit_year_hint=explicit_hint,
        )
        if due is None:
            continue
        if (
            warning is None
            and raw_text
            and not _find_weekday_mentions(raw_due, due.month, due.day)
        ):
            due, warning = reconcile_date_weekday(
                due, raw_text, reference_date=reference_date
            )
            if due is None:
                continue
        rows.append(
            BnplInstallmentRow(
                merchant=merchant,
                amount=amount,
                due_date=due,
                installment_number=counter[0],
                total_installments=counter[1],
                currency="AUD",
                warnings=(warning,) if warning else (),
            )
        )
    return rows


def _is_avatar_or_noise_line(line: str, next_line: str | None = None) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    low = stripped.lower()
    if low in _NOISE_PHRASES or _DUE_IN_DAYS_RE.match(low) or _CLOCK_RE.match(low):
        return True
    # Single-letter avatar initials (M, A, U, C) or numeric battery badge.
    if len(stripped) == 1 or stripped.isdigit():
        return True
    # Brand logo text duplicated right above the actual merchant name (e.g.
    # "ebay" above "eBay", "BING LEE" above "Bing Lee Electrics ...").
    if next_line is not None:
        next_clean = _INLINE_AMOUNT_RE.sub("", next_line).strip().lower()
        if next_clean and next_clean != low and next_clean.startswith(low):
            return True
        if next_clean == low and stripped.islower():
            return True
    return False


def parse_afterpay_orders_text(
    text: str, *, reference_date: date | None = None
) -> list[BnplInstallmentRow]:
    """Parse OCR text of an Afterpay 'Your orders' instalment list screenshot."""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return []

    # Locate every "n of m • <date>" anchor line first.
    anchors: list[tuple[int, int, int, str]] = []
    explicit_hint: tuple[int, int] | None = None
    for idx, line in enumerate(raw_lines):
        match = _ANCHOR_LINE_RE.match(line)
        if not match:
            continue
        n, m = int(match.group(1)), int(match.group(2))
        if not (1 <= n <= m and m >= 2):
            continue
        date_part = match.group(3).strip()
        hint = _extract_explicit_year_month(date_part)
        if hint is not None and explicit_hint is None:
            explicit_hint = hint
        anchors.append((idx, n, m, date_part))

    if not anchors:
        return []

    # Identify standalone amount lines that belong to the summary header
    # ("$1,341.03" right before "Total you owe", "$643.20" before "Due in 15 days").
    summary_indices: set[int] = set()
    for idx, line in enumerate(raw_lines):
        if _STANDALONE_AMOUNT_RE.match(line) and idx + 1 < len(raw_lines):
            nxt = raw_lines[idx + 1].lower()
            if nxt == "total you owe" or _DUE_IN_DAYS_RE.match(nxt):
                summary_indices.add(idx)

    rows: list[BnplInstallmentRow] = []
    consumed_after: set[int] = set()
    for pos, (anchor_idx, n, m, date_part) in enumerate(anchors):
        due, warning = _parse_bnpl_date_checked(
            date_part,
            reference_date=reference_date,
            explicit_year_hint=explicit_hint,
        )
        if due is None:
            continue

        prev_anchor_idx = anchors[pos - 1][0] if pos > 0 else -1
        next_anchor_idx = (
            anchors[pos + 1][0] if pos + 1 < len(anchors) else len(raw_lines)
        )

        # Collect candidate lines between the previous anchor and this anchor.
        merchant: str | None = None
        amount: Decimal | None = None
        window_start = prev_anchor_idx + 1
        candidate_lines: list[tuple[int, str]] = [
            (i, raw_lines[i])
            for i in range(window_start, anchor_idx)
            if i not in consumed_after and i not in summary_indices
        ]

        # Walk backwards from the anchor to find the merchant line (and inline/adjacent amount).
        for offset in range(len(candidate_lines) - 1, -1, -1):
            line_idx, line = candidate_lines[offset]
            if _STANDALONE_AMOUNT_RE.match(line):
                if amount is None:
                    amount = _parse_bnpl_amount(line)
                continue
            next_candidate = (
                candidate_lines[offset + 1][1]
                if offset + 1 < len(candidate_lines)
                else None
            )
            if _is_avatar_or_noise_line(line, next_candidate):
                continue
            inline = _INLINE_AMOUNT_RE.search(line)
            if inline:
                if amount is None:
                    amount = _parse_bnpl_amount(inline.group(1))
                cleaned_m = _clean_merchant(_INLINE_AMOUNT_RE.sub("", line).strip())
            else:
                cleaned_m = _clean_merchant(line)
            if cleaned_m and not _is_noise_merchant(cleaned_m):
                merchant = cleaned_m
                break

        # If amount sits on the line immediately after the anchor (e.g. "Pay $28.50" button).
        if amount is None and anchor_idx + 1 < next_anchor_idx:
            after_idx = anchor_idx + 1
            if after_idx not in summary_indices and _STANDALONE_AMOUNT_RE.match(
                raw_lines[after_idx]
            ):
                amount = _parse_bnpl_amount(raw_lines[after_idx])
                consumed_after.add(after_idx)

        if merchant is None or amount is None:
            # Clipped/incomplete row at top or bottom edge — skip.
            continue

        rows.append(
            BnplInstallmentRow(
                merchant=merchant,
                amount=amount,
                due_date=due,
                installment_number=n,
                total_installments=m,
                currency="AUD",
                warnings=(warning,) if warning else (),
            )
        )

    return rows


def _normalize_merchant_for_compare(value: str) -> tuple[str, bool]:
    """Return (normalized_text, was_truncated_with_ellipsis)."""
    stripped = _clean_merchant(value)
    truncated = stripped.endswith("...") or stripped.endswith("…")
    stripped = stripped.rstrip(".… ").lower()
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped, truncated


def merchants_match(a: str, b: str) -> bool:
    """Compare two Afterpay merchant names, tolerating ellipsis truncation.

    Handles width changes between 'Pay $XX.XX' and '$XX.XX' rows (e.g.
    'Bing Lee Electri...' vs 'Bing Lee Electrics ...' vs 'Bing Lee Electrics Pty Limited')
    without merging distinct stores such as 'AMCALPHARMA...' vs 'AMCAL MARAL...'.
    """
    norm_a, trunc_a = _normalize_merchant_for_compare(a)
    norm_b, trunc_b = _normalize_merchant_for_compare(b)
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True
    if trunc_a and len(norm_a) >= 4 and norm_b.startswith(norm_a):
        return True
    if trunc_b and len(norm_b) >= 4 and norm_a.startswith(norm_b):
        return True
    return False
