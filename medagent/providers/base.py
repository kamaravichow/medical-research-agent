"""Shared HTTP plumbing for the provider clients."""

from __future__ import annotations

import asyncio
import html
import re
from typing import Any

import httpx

from .. import __version__

USER_AGENT = f"medagent/{__version__} (+https://github.com/kamaravichow/medical-research-agent)"
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """A provider failed after retries; the message is safe to show a user."""


def make_client(timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=10.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    retries: int = 2,
    provider: str = "provider",
    ok_statuses: tuple[int, ...] = (),
) -> httpx.Response:
    """Send a request, retrying rate limits and transient 5xx with backoff."""
    delay = 0.6
    for attempt in range(retries + 1):
        try:
            response = await client.request(method, url, params=params)
        except httpx.TransportError as exc:
            if attempt == retries:
                raise ProviderError(f"{provider}: network error ({exc.__class__.__name__})") from exc
        else:
            if response.status_code < 400 or response.status_code in ok_statuses:
                return response
            if response.status_code not in _RETRY_STATUS or attempt == retries:
                raise ProviderError(f"{provider}: HTTP {response.status_code}")
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), 5.0)
        await asyncio.sleep(delay)
        delay *= 2
    raise ProviderError(f"{provider}: exhausted retries")  # pragma: no cover


async def get_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Any:
    response = await request(client, "GET", url, **kwargs)
    return response.json()


_TAG = re.compile(r"<[^>]+>")


def strip_tags(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", text))).strip() or None


def first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def to_int(value: Any) -> int | None:
    try:
        return int(str(value)[:4]) if value not in (None, "") else None
    except ValueError:
        return None
