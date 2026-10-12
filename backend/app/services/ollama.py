"""Minimal client for the local Ollama HTTP API (shared by AI features)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class OllamaConfig:
    """Resolved Ollama connection settings (DB override → env)."""

    base_url: str
    model: str
    ocr_model: str
    text_model: str
    timeout: float


class OllamaError(RuntimeError):
    """Base error for Ollama calls."""


class OllamaUnavailable(OllamaError):
    """The server could not be reached."""


class OllamaBadResponse(OllamaError):
    """The server answered, but not with usable JSON."""


def generate_json(
    *,
    config: OllamaConfig,
    prompt: str,
    model: str | None = None,
    images: list[str] | None = None,
    schema: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run a single non-streaming generation and parse the JSON response.

    `images` are base64 strings; `schema` becomes Ollama's structured-output
    `format` so the model is constrained to valid JSON. `model` overrides the
    config's primary model (used for the OCR/text phases).
    """
    payload: dict[str, Any] = {
        "model": model or config.model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    if images:
        payload["images"] = images
    if schema:
        payload["format"] = schema

    try:
        response = httpx.post(
            f"{config.base_url}/api/generate",
            json=payload,
            timeout=timeout if timeout is not None else config.timeout,
        )
    except httpx.HTTPError as exc:
        raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc

    if response.status_code != 200:
        raise OllamaBadResponse(
            f"Ollama HTTP {response.status_code}: {response.text[:200]}"
        )

    try:
        body = response.json()
        # Thinking models (e.g. qwen3-vl with a format schema) can put the
        # structured output in `thinking` and leave `response` empty; prefer
        # the answer but fall back so both layouts work.
        raw = body.get("response") or body.get("thinking")
    except (ValueError, TypeError) as exc:
        raise OllamaBadResponse("Ollama returned no response field") from exc
    if not raw:
        raise OllamaBadResponse("Ollama returned no response field")

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise OllamaBadResponse(f"Model did not return JSON: {str(raw)[:200]}") from exc
    if not isinstance(parsed, dict):
        raise OllamaBadResponse("Model returned JSON that is not an object")
    return parsed


def list_models(*, base_url: str, timeout: float = 5.0) -> list[str]:
    """Names of locally available models; raises OllamaUnavailable on failure."""
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=timeout)
    except httpx.HTTPError as exc:
        raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc
    if response.status_code != 200:
        raise OllamaBadResponse(f"Ollama HTTP {response.status_code}")
    try:
        return [str(m["name"]) for m in response.json().get("models", [])]
    except (ValueError, KeyError, TypeError) as exc:
        raise OllamaBadResponse("Unexpected /api/tags payload") from exc
