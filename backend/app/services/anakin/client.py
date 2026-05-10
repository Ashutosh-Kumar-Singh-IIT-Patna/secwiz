"""Shared :class:`httpx.AsyncClient` plus a tiny polling helper.

Every Anakin endpoint takes the same ``X-API-Key`` header, so we centralise
the client construction here and bound concurrency with a per-process
semaphore.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from ...config import get_settings

log = logging.getLogger(__name__)


class AnakinError(RuntimeError):
    def __init__(self, status: int, payload: Any) -> None:
        super().__init__(f"anakin {status}: {payload!r}")
        self.status = status
        self.payload = payload


class AnakinClient:
    """Thin convenience wrapper around :class:`httpx.AsyncClient`.

    Use as an async context manager (one per logical run) so timeouts /
    semaphore are scoped correctly. Each Anakin product (Wire, URL Scraper,
    etc.) lives in its own module and accepts an :class:`AnakinClient`.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        concurrency: int | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.ANAKIN_API_KEY
        self._base_url = (base_url or settings.ANAKIN_BASE_URL).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.HTTP_TIMEOUT_SECONDS
        self._semaphore = asyncio.Semaphore(
            concurrency if concurrency is not None else settings.INGEST_CONCURRENCY
        )
        self._http: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def __aenter__(self) -> "AnakinClient":
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"X-API-Key": self._api_key} if self._api_key else {},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @asynccontextmanager
    async def _slot(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http is None:
            raise RuntimeError("AnakinClient not entered")
        async with self._semaphore:
            yield self._http

    async def get(self, path: str, **kwargs: Any) -> Any:
        async with self._slot() as http:
            response = await http.get(path, **kwargs)
        return _unwrap(response)

    async def post(self, path: str, **kwargs: Any) -> Any:
        async with self._slot() as http:
            response = await http.post(path, **kwargs)
        return _unwrap(response)


def _unwrap(response: httpx.Response) -> Any:
    if 200 <= response.status_code < 300:
        if not response.content:
            return None
            # 202 Accepted with body is allowed; both branches fall through.
        try:
            return response.json()
        except ValueError:
            return response.text
    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    log.warning(
        "anakin error status=%s url=%s payload=%s",
        response.status_code,
        response.request.url if response.request else "?",
        payload,
    )
    raise AnakinError(response.status_code, payload)


async def poll_until_done(
    fetcher: Callable[[], Awaitable[dict[str, Any]]],
    *,
    is_done: Callable[[dict[str, Any]], bool] | None = None,
    interval_s: float | None = None,
    max_s: float | None = None,
) -> dict[str, Any]:
    """Generic poll loop for Anakin async jobs.

    The job-shape across products is consistent: a JSON object with a
    ``status`` field that goes through ``pending``/``processing`` and ends in
    ``completed`` or ``failed``. The default ``is_done`` predicate checks for
    those terminal values so callers rarely need to override it.
    """

    settings = get_settings()
    interval = interval_s if interval_s is not None else settings.ANAKIN_POLL_INTERVAL_SECONDS
    deadline = max_s if max_s is not None else settings.ANAKIN_POLL_MAX_SECONDS
    is_done_fn = is_done or _default_is_done

    elapsed = 0.0
    while True:
        payload = await fetcher()
        if is_done_fn(payload):
            return payload
        if elapsed >= deadline:
            payload.setdefault("status", "timeout")
            return payload
        await asyncio.sleep(interval)
        elapsed += interval


def _default_is_done(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    return status in {"completed", "failed", "succeeded", "error", "timeout"}
