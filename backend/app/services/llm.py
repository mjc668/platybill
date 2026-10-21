"""Provider-agnostic LLM client for bill extraction.

Providers: "ollama" (native /api/generate), "openai" / "opencode"
(OpenAI-compatible /chat/completions + /models), "anthropic" (Messages API),
"google" (Gemini generateContent). OpenAI-compatible covers OpenAI, opencode
servers, and any local OpenAI-style endpoint — only the base URL differs.

Errors mirror the Ollama shapes callers already handle: LlmUnavailable for
transport failures, LlmBadResponse for unusable payloads. LlmError is the
base; both subclass it so `except LlmError` catches everything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import httpx

LlmProvider = Literal["ollama", "openai", "anthropic", "google", "opencode"]

PROVIDERS: tuple[str, ...] = ("ollama", "openai", "anthropic", "google", "opencode")

# Provider ids that speak the OpenAI chat-completions dialect.
OPENAI_COMPATIBLE: frozenset[str] = frozenset({"openai", "opencode"})

DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
}

DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class LlmConfig:
    """Resolved LLM connection settings (DB override → env)."""

    provider: str = "ollama"
    model: str = ""
    base_url: str | None = None
    api_key: str | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS


class LlmError(RuntimeError):
    """Base error for LLM calls."""


class LlmUnavailable(LlmError):
    """The provider could not be reached."""


class LlmBadResponse(LlmError):
    """The provider answered, but not with usable output."""


def effective_base_url(config: LlmConfig) -> str:
    if config.base_url:
        return config.base_url.rstrip("/")
    return DEFAULT_BASE_URLS.get(config.provider, "").rstrip("/")


def _openai_messages(
    prompt: str, images: list[str] | None, schema: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Text (+optional base64 PNGs) plus a JSON-only instruction when needed."""
    text = prompt
    if schema is not None:
        text += (
            "\n\nRespond with a single JSON object matching this schema, "
            "no other text:\n" + json.dumps(schema)
        )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for image in images or []:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image}"},
            }
        )
    return [{"role": "user", "content": content}]


def _openai_generate(
    *,
    config: LlmConfig,
    base_url: str,
    prompt: str,
    model: str,
    images: list[str] | None,
    schema: dict[str, Any] | None,
    timeout: float,
) -> str:
    body: dict[str, Any] = {
        "model": model,
        "messages": _openai_messages(prompt, images, schema),
        "temperature": 0,
    }
    if schema is not None:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    try:
        response = httpx.post(
            f"{base_url}/chat/completions", json=body, headers=headers, timeout=timeout
        )
    except httpx.HTTPError as exc:
        raise LlmUnavailable(f"LLM request failed: {exc}") from exc
    if response.status_code == 401:
        raise LlmBadResponse("LLM rejected the API key (401)")
    if response.status_code != 200:
        raise LlmBadResponse(f"LLM HTTP {response.status_code}: {response.text[:200]}")
    try:
        choices = response.json()["choices"]
        text = choices[0]["message"]["content"] or ""
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise LlmBadResponse("LLM returned no message content") from exc
    if not str(text).strip():
        raise LlmBadResponse("LLM returned an empty response")
    return str(text)


def _anthropic_generate(
    *,
    config: LlmConfig,
    base_url: str,
    prompt: str,
    model: str,
    images: list[str] | None,
    schema: dict[str, Any] | None,
    timeout: float,
) -> str:
    text = prompt
    if schema is not None:
        text += (
            "\n\nRespond with a single JSON object matching this schema, "
            "no other text:\n" + json.dumps(schema)
        )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for image in images or []:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image,
                },
            }
        )
    headers = {
        "x-api-key": config.api_key or "",
        "anthropic-version": "2023-06-01",
    }
    try:
        response = httpx.post(
            f"{base_url}/v1/messages",
            json={
                "model": model,
                "max_tokens": 2048,
                "temperature": 0,
                "messages": [{"role": "user", "content": content}],
            },
            headers=headers,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise LlmUnavailable(f"LLM request failed: {exc}") from exc
    if response.status_code == 401:
        raise LlmBadResponse("LLM rejected the API key (401)")
    if response.status_code != 200:
        raise LlmBadResponse(f"LLM HTTP {response.status_code}: {response.text[:200]}")
    try:
        blocks = response.json()["content"]
        text_out = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except (ValueError, KeyError, TypeError) as exc:
        raise LlmBadResponse("LLM returned no text content") from exc
    if not text_out.strip():
        raise LlmBadResponse("LLM returned an empty response")
    return text_out


def _google_generate(
    *,
    config: LlmConfig,
    base_url: str,
    prompt: str,
    model: str,
    images: list[str] | None,
    schema: dict[str, Any] | None,
    timeout: float,
) -> str:
    text = prompt
    if schema is not None:
        text += (
            "\n\nRespond with a single JSON object matching this schema, "
            "no other text:\n" + json.dumps(schema)
        )
    parts: list[dict[str, Any]] = [{"text": text}]
    for image in images or []:
        parts.append({"inline_data": {"mime_type": "image/png", "data": image}})
    url = f"{base_url}/v1beta/models/{model}:generateContent"
    if config.api_key:
        url += f"?key={config.api_key}"
    try:
        response = httpx.post(
            url,
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0},
            },
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise LlmUnavailable(f"LLM request failed: {exc}") from exc
    if response.status_code in (400, 401, 403):
        raise LlmBadResponse(
            f"LLM rejected the request ({response.status_code}): "
            f"{response.text[:200]}"
        )
    if response.status_code != 200:
        raise LlmBadResponse(f"LLM HTTP {response.status_code}: {response.text[:200]}")
    try:
        parts_out = response.json()["candidates"][0]["content"]["parts"]
        text_out = "".join(p.get("text", "") for p in parts_out)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise LlmBadResponse("LLM returned no text content") from exc
    if not text_out.strip():
        raise LlmBadResponse("LLM returned an empty response")
    return text_out


def _ollama_generate(
    *,
    config: LlmConfig,
    prompt: str,
    model: str,
    images: list[str] | None,
    schema: dict[str, Any] | None,
    timeout: float,
) -> str:
    from app.services import ollama as ollama_client

    base_url = (config.base_url or "").rstrip("/")
    ollama_config = ollama_client.OllamaConfig(
        base_url=base_url,
        model=model,
        ocr_model=model,
        text_model=model,
        timeout=timeout,
    )
    try:
        if schema is not None:
            payload = ollama_client.generate_json(
                config=ollama_config,
                prompt=prompt,
                model=model,
                images=images,
                schema=schema,
            )
            return json.dumps(payload)
        return ollama_client.generate_text(
            config=ollama_config, prompt=prompt, model=model, images=images
        )
    except ollama_client.OllamaUnavailable as exc:
        raise LlmUnavailable(str(exc)) from exc
    except ollama_client.OllamaError as exc:
        raise LlmBadResponse(str(exc)) from exc


def _generate_raw(
    *,
    config: LlmConfig,
    prompt: str,
    model: str | None,
    images: list[str] | None,
    schema: dict[str, Any] | None,
    timeout: float | None,
) -> str:
    resolved_model = model or config.model
    resolved_timeout = timeout if timeout is not None else config.timeout
    base_url = effective_base_url(config)
    if config.provider == "ollama":
        return _ollama_generate(
            config=config,
            prompt=prompt,
            model=resolved_model,
            images=images,
            schema=schema,
            timeout=resolved_timeout,
        )
    if config.provider in OPENAI_COMPATIBLE:
        return _openai_generate(
            config=config,
            base_url=base_url,
            prompt=prompt,
            model=resolved_model,
            images=images,
            schema=schema,
            timeout=resolved_timeout,
        )
    if config.provider == "anthropic":
        return _anthropic_generate(
            config=config,
            base_url=base_url,
            prompt=prompt,
            model=resolved_model,
            images=images,
            schema=schema,
            timeout=resolved_timeout,
        )
    if config.provider == "google":
        return _google_generate(
            config=config,
            base_url=base_url,
            prompt=prompt,
            model=resolved_model,
            images=images,
            schema=schema,
            timeout=resolved_timeout,
        )
    raise LlmBadResponse(f"Unknown LLM provider '{config.provider}'")


def generate_text(
    *,
    config: LlmConfig,
    prompt: str,
    model: str | None = None,
    images: list[str] | None = None,
    timeout: float | None = None,
) -> str:
    """Single generation returning raw text."""
    return _generate_raw(
        config=config,
        prompt=prompt,
        model=model,
        images=images,
        schema=None,
        timeout=timeout,
    )


def generate_json(
    *,
    config: LlmConfig,
    prompt: str,
    model: str | None = None,
    images: list[str] | None = None,
    schema: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Single generation parsed as a JSON object (fences tolerated)."""
    raw = _generate_raw(
        config=config,
        prompt=prompt,
        model=model,
        images=images,
        schema=schema,
        timeout=timeout,
    )
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LlmBadResponse(f"Model did not return JSON: {raw[:200]}") from exc
    if not isinstance(parsed, dict):
        raise LlmBadResponse("Model returned JSON that is not an object")
    return parsed


def list_models(
    *,
    config: LlmConfig,
    timeout: float = 5.0,
) -> list[str]:
    """Model ids the provider reports; raises LlmUnavailable on failure."""
    from app.services import ollama as ollama_client

    base_url = effective_base_url(config)
    if config.provider == "ollama":
        try:
            return ollama_client.list_models(base_url=base_url, timeout=timeout)
        except ollama_client.OllamaUnavailable as exc:
            raise LlmUnavailable(str(exc)) from exc
        except ollama_client.OllamaError as exc:
            raise LlmBadResponse(str(exc)) from exc
    if config.provider in OPENAI_COMPATIBLE:
        headers = (
            {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        )
        try:
            response = httpx.get(f"{base_url}/models", headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            raise LlmUnavailable(f"LLM request failed: {exc}") from exc
        if response.status_code != 200:
            raise LlmBadResponse(f"LLM HTTP {response.status_code}")
        try:
            return [str(m["id"]) for m in response.json().get("data", [])]
        except (ValueError, KeyError, TypeError) as exc:
            raise LlmBadResponse("Unexpected /models payload") from exc
    if config.provider == "anthropic":
        # No list endpoint on the Messages API; the model id is user-supplied.
        return [config.model] if config.model else []
    if config.provider == "google":
        url = f"{base_url}/v1beta/models"
        if config.api_key:
            url += f"?key={config.api_key}"
        try:
            response = httpx.get(url, timeout=timeout)
        except httpx.HTTPError as exc:
            raise LlmUnavailable(f"LLM request failed: {exc}") from exc
        if response.status_code != 200:
            raise LlmBadResponse(f"LLM HTTP {response.status_code}")
        try:
            return [
                str(m["name"]).removeprefix("models/")
                for m in response.json().get("models", [])
            ]
        except (ValueError, KeyError, TypeError) as exc:
            raise LlmBadResponse("Unexpected models payload") from exc
    raise LlmBadResponse(f"Unknown LLM provider '{config.provider}'")
