"""HTTP helpers shared by the four fetchers.

Two rules are baked in here rather than repeated per source:

* redirects are followed (OFAC hands the real file to a signed S3 URL and
  answers 302; without following it you get zero bytes);
* HTTP 200 is never accepted on its own. A wrong path on the OFAC and USITC
  hosts returns 200 with an empty body, so every response is checked against a
  byte floor before a caller sees it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from fleet.sync.gate import DataSourceUnhealthy

USER_AGENT = (
    "tariff-reclassification-fleet/1.0 "
    "(All Things Agentic hackathon; https://github.com/)"
)

#: No source publishes a rate limit, so the fetchers self-throttle: one
#: connection, at least this many seconds between requests to the same host.
MIN_REQUEST_INTERVAL = 0.35

DEFAULT_TIMEOUT = 120

_last_request_at: dict[str, float] = {}


@dataclass(frozen=True)
class Response:
    url: str
    body: bytes
    last_modified: datetime | None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8-sig")


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _throttle(url: str) -> None:
    host = url.split("/")[2] if "//" in url else url
    previous = _last_request_at.get(host)
    now = time.monotonic()
    if previous is not None:
        wait = MIN_REQUEST_INTERVAL - (now - previous)
        if wait > 0:
            time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def _parse_last_modified(headers) -> datetime | None:
    raw = headers.get("Last-Modified") if headers else None
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get(
    session: requests.Session,
    url: str,
    *,
    min_bytes: int = 1,
    params: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    source: str = "http",
) -> Response:
    """GET `url`, following redirects, and refuse anything short or non-200."""
    _throttle(url)
    try:
        response = session.get(
            url, params=params, allow_redirects=True, timeout=timeout
        )
    except requests.RequestException as exc:
        raise DataSourceUnhealthy(f"{source}: request failed for {url}: {exc}") from exc

    if response.status_code != 200:
        raise DataSourceUnhealthy(
            f"{source}: HTTP {response.status_code} for {response.url}"
        )

    body = response.content
    if len(body) < max(1, min_bytes):
        raise DataSourceUnhealthy(
            f"{source}: HTTP 200 with {len(body)} bytes for {response.url}, "
            f"below the {min_bytes}-byte floor; a 200 is not proof of a payload"
        )

    return Response(
        url=response.url,
        body=body,
        last_modified=_parse_last_modified(response.headers),
    )


def get_json(session: requests.Session, url: str, **kwargs):
    response = get(session, url, **kwargs)
    source = kwargs.get("source", "http")
    try:
        return json.loads(response.text)
    except ValueError as exc:
        raise DataSourceUnhealthy(
            f"{source}: response from {response.url} is not valid JSON: {exc}"
        ) from exc
