"""Bill document → structured fields via a local Ollama model.

Digital PDFs take the text path (pypdf → text model). Scans and photos are
rendered to PNG (pypdfium2) and sent to the vision model. If the primary
vision parse fails, a two-phase fallback runs OCR first and feeds the text to
the text model. Nothing here writes to the database.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.ollama import (
    OllamaConfig,
    OllamaError,
    OllamaUnavailable,
    generate_json,
    generate_text,
)

logger = logging.getLogger(__name__)

MAX_PAGES = 2
TARGET_LONGEST_SIDE = 1540

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "provider": {
            "type": ["string", "null"],
            "description": "Company or utility name that issued the bill",
        },
        "amount": {
            "type": ["number", "null"],
            "description": "Total amount due, digits only (no currency symbol)",
        },
        "currency": {
            "type": ["string", "null"],
            "description": "ISO 4217 code such as AUD, PLN, EUR",
        },
        "due_date": {
            "type": ["string", "null"],
            "description": "Payment due date in YYYY-MM-DD form",
        },
        "period": {
            "type": ["string", "null"],
            "description": "Billing period as YYYY-MM when shown",
        },
        "confidence": {
            "type": "number",
            "description": "0-1 confidence in the extracted fields",
        },
    },
    "required": ["provider", "amount", "due_date"],
}

# NuExtract-family models are template extractors: they expect a template with
# typed fields and produce JSON themselves, so the structured-output schema
# must be omitted (it makes them return an empty response).
_NUEXTRACT_TEMPLATE = (
    "Extract the following fields from this document:\n"
    '{"provider": "verbatim-string", "amount": "number", '
    '"currency": "verbatim-string", "due_date": "date-time", '
    '"period": "verbatim-string", "confidence": "number"}\n'
    "Return only the JSON object."
)

_INSTRUCTIONS = (
    "Extract the bill details from this document. Return only the JSON object. "
    "amount is the total amount due as a decimal with cents (e.g. 87.30, no currency symbol). "
    "due_date is the payment due date in ISO format (YYYY-MM-DD). "
    "period is the billing period as YYYY-MM when present. "
    "currency is the ISO code when identifiable. "
    "confidence is your confidence from 0 to 1."
)


@dataclass
class ExtractedBill:
    provider: str | None
    amount: Decimal | None
    currency: str | None
    due_date: date | None
    period: str | None
    confidence: float
    raw_text: str | None = None


def _is_nuextract(model: str) -> bool:
    return "nuextract" in model.lower()


def _prompt_and_schema(
    model: str, *, document_text: str | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Prompt + structured-output schema for a model family.

    NuExtract gets its template prompt and no schema; everything else gets the
    instruction prompt constrained by the JSON schema.
    """
    if _is_nuextract(model):
        return _NUEXTRACT_TEMPLATE, None
    prompt = _INSTRUCTIONS
    if document_text is not None:
        prompt = f"{_INSTRUCTIONS}\n\nDocument text:\n---\n{document_text}\n---"
    return prompt, EXTRACTION_SCHEMA


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


_MONTHS = {
    name.lower(): index
    for index, name in enumerate(
        (
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
        ),
        start=1,
    )
}


def _normalize_period(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    match = re.match(r"^(\d{4})-(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    # "01 Oct 2026 - 31 Oct 2026" and friends: take the first month+year.
    month_match = re.search(r"([A-Za-z]{3,9})\s+(\d{4})", text)
    if month_match:
        month = _MONTHS.get(
            month_match.group(1).lower()[:3]
            if len(month_match.group(1)) > 3
            else month_match.group(1).lower()
        )
        if month is None:
            for name, index in _MONTHS.items():
                if name.startswith(month_match.group(1).lower()[:3]):
                    month = index
                    break
        if month is not None:
            return f"{month_match.group(2)}-{month:02d}"
    return None


def _parse(payload: dict[str, Any], *, raw_text: str | None = None) -> ExtractedBill:
    currency = payload.get("currency")
    if currency is not None:
        currency = str(currency).strip().upper()[:10] or None
    confidence = payload.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else 0.5
    except (TypeError, ValueError):
        confidence_value = 0.5
    return ExtractedBill(
        provider=(
            (str(payload["provider"]).strip() or None)
            if payload.get("provider")
            else None
        ),
        amount=_to_decimal(payload.get("amount")),
        currency=currency,
        due_date=_to_date(payload.get("due_date")),
        period=_normalize_period(payload.get("period")),
        confidence=max(0.0, min(1.0, confidence_value)),
        raw_text=raw_text,
    )


def pdf_text(data: bytes) -> str:
    """Extracted text of the first pages; empty string for scans."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — pypdf raises many shapes
        logger.info("PDF parse failed: %s", exc)
        return ""
    chunks: list[str] = []
    for page in reader.pages[:MAX_PAGES]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — per-page tolerance
            continue
    return "\n".join(chunks).strip()


def render_pdf_png(data: bytes) -> bytes:
    """First page rendered to PNG at ~1540 px on the longest side."""
    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    pdf = pdfium.PdfDocument(data)
    if len(pdf) == 0:
        raise ValueError("PDF has no pages")
    page = pdf[0]
    width, height = page.get_size()
    scale = TARGET_LONGEST_SIDE / max(width, height)
    bitmap = page.render(scale=max(scale, 1.0))
    image = bitmap.to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def extract_from_text(text: str, *, config: OllamaConfig) -> ExtractedBill:
    prompt, schema = _prompt_and_schema(config.text_model, document_text=text)
    payload = generate_json(
        config=config,
        model=config.text_model,
        prompt=prompt,
        schema=schema,
    )
    return _parse(payload, raw_text=text)


def extract_from_image(image: bytes, *, config: OllamaConfig) -> ExtractedBill:
    encoded = base64.b64encode(image).decode()
    prompt, schema = _prompt_and_schema(config.model)
    payload = generate_json(
        config=config,
        prompt=prompt,
        images=[encoded],
        schema=schema,
    )
    return _parse(payload)


def _extract_image_two_phase(image: bytes, *, config: OllamaConfig) -> ExtractedBill:
    """OCR with the vision model, then extract with the text model."""
    encoded = base64.b64encode(image).decode()
    text = generate_text(
        config=config,
        model=config.ocr_model,
        prompt="Extract all text from this document, preserving layout order.",
        images=[encoded],
    )
    if not text.strip():
        raise OllamaError("OCR model returned no text")
    return extract_from_text(text, config=config)


def extract_document(
    data: bytes,
    *,
    config: OllamaConfig,
    content_type: str | None = None,
    filename: str | None = None,
) -> ExtractedBill:
    """Extract from a PDF or image, choosing text vs vision automatically."""
    is_pdf = (content_type == "application/pdf") or (filename or "").lower().endswith(
        ".pdf"
    )
    if is_pdf:
        text = pdf_text(data)
        if len(text) >= 40:
            return extract_from_text(text, config=config)
        image = render_pdf_png(data)
    else:
        image = data

    try:
        return extract_from_image(image, config=config)
    except OllamaUnavailable:
        raise
    except OllamaError as exc:
        logger.info("Primary vision parse failed (%s); trying two-phase", exc)
        return _extract_image_two_phase(image, config=config)
