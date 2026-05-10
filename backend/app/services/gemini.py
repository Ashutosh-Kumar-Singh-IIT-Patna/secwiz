"""Gemini ``generateContent`` wrapper.

V1 uses Gemini in exactly one place: as a second-opinion judge over
already-scored security events (see :mod:`app.services.pipeline.judge`).
We force JSON output via ``response_mime_type`` so the caller can
``json.loads()`` the response without prompt-engineering escape hatches.

The wrapper is intentionally thin — no SDK dependency, just ``httpx`` —
so the project keeps a single async HTTP client family.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


class GeminiError(RuntimeError):
    def __init__(self, status: int, payload: Any) -> None:
        super().__init__(f"gemini {status}: {payload!r}")
        self.status = status
        self.payload = payload


async def generate_json(
    prompt: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
    max_output_tokens: int = 2048,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Call ``generateContent`` and return the parsed JSON object.

    Returns the decoded dict on success. Raises :class:`GeminiError` for
    HTTP failures and :class:`ValueError` if the response can't be parsed
    as JSON. Callers should catch both and gracefully degrade.

    .. note::
        ``maxOutputTokens`` includes hidden "thinking" tokens for thinking
        models (e.g. ``gemini-3-flash-preview`` charges ~200-1500 tokens
        of internal reasoning before emitting the JSON envelope). Default
        of 2048 is sized for our judge prompt + a couple of K of thinking
        + a ~200-token JSON answer. Bump it if the prompt grows.
    """

    settings = get_settings()
    key = api_key if api_key is not None else settings.GEMINI_API_KEY
    if not key:
        raise GeminiError(0, "GEMINI_API_KEY not set")

    base = settings.GEMINI_BASE_URL.rstrip("/")
    chosen_model = model or settings.GEMINI_MODEL
    url = f"{base}/models/{chosen_model}:generateContent"
    request_timeout = timeout if timeout is not None else settings.HTTP_TIMEOUT_SECONDS

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
        },
    }
    # Header auth keeps the key out of URL logs and matches the documented
    # form on https://ai.google.dev/gemini-api/docs/api-key.
    headers = {"X-goog-api-key": key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=request_timeout) as http:
        response = await http.post(url, headers=headers, json=body)

    if not 200 <= response.status_code < 300:
        try:
            err_payload: Any = response.json()
        except ValueError:
            err_payload = response.text
        log.warning("gemini error status=%s payload=%s", response.status_code, err_payload)
        raise GeminiError(response.status_code, err_payload)

    payload = response.json()
    text = _extract_text(payload)
    finish_reason = _finish_reason(payload)
    if not text:
        raise ValueError(
            f"gemini returned empty content (finish_reason={finish_reason!r}): "
            f"{payload!r}"
        )

    try:
        return json.loads(text)
    except ValueError as err:
        # MAX_TOKENS is the most common culprit — surface it loudly so the
        # caller knows to bump ``max_output_tokens`` rather than retry.
        log.warning(
            "gemini returned non-JSON content (finish_reason=%s, len=%d): %s",
            finish_reason,
            len(text),
            text[:400],
        )
        raise ValueError(
            f"gemini returned non-JSON (finish_reason={finish_reason}): {err}"
        ) from err


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull the first text part out of the documented response shape.

    Schema (per https://ai.google.dev/api/generate-content):
    ``{"candidates": [{"content": {"parts": [{"text": "..."}, ...]}}, ...]}``.

    We tolerate empty/missing fields and just return ``""`` so callers can
    treat that as a soft failure.
    """

    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    chunks: list[str] = []
    for part in parts:
        text = part.get("text") if isinstance(part, dict) else None
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks).strip()


def _finish_reason(payload: dict[str, Any]) -> str:
    """E.g. ``STOP`` (clean), ``MAX_TOKENS`` (truncated), ``SAFETY`` (blocked)."""

    candidates = payload.get("candidates") or []
    if not candidates:
        return "UNKNOWN"
    return str(candidates[0].get("finishReason") or "UNKNOWN")
