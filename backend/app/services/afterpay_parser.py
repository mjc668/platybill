from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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

    def to_dict(self) -> dict[str, Any]:
        return {
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


def parse_afterpay(html_body: str, text_body: str = "") -> ExtractedBnpl | None:
    """Extract Afterpay installment plan from HTML or plain-text body."""
    if html_body:
        extracted = _parse_from_html(html_body)
        if extracted is not None:
            return extracted

    if text_body:
        return _parse_from_text(text_body)

    return None


def _parse_from_html(html_content: str) -> ExtractedBnpl | None:
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
    for i in range(1, 10):
        amount_str = data.get(f"email-payment{i}-amount")
        date_str = data.get(f"email-payment{i}-date")
        status_str = data.get(f"email-payment{i}-status")
        if not amount_str or not date_str:
            break

        amt = _parse_amount(amount_str)
        dt = _parse_date(date_str)
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
    )


def _parse_from_text(text: str) -> ExtractedBnpl | None:
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
    payment_blocks = re.findall(
        r"(FIRST|SECOND|THIRD|FOURTH|\d+(?:st|nd|rd|th))\s+PAYMENT[\s\S]*?\$?(\d+\.\d{2})[\s\S]*?DUE DATE:\s*([A-Za-z]+,\s*\d{1,2}/\d{1,2}/\d{4}|\d{1,2}/\d{1,2}/\d{4})",
        text,
        re.IGNORECASE,
    )

    for idx, (_, amount_str, date_str) in enumerate(payment_blocks, start=1):
        amt = _parse_amount(amount_str)
        dt = _parse_date(date_str)
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
    )
