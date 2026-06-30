from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests


class ResoClient:
    """
    RESO Web API (OData) client for incremental MLS data pulls.

    Bearer-authenticated, with pagination via ``@odata.nextLink`` and
    retry/backoff on 429 and server errors.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._session: Optional[requests.Session] = None

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #
    @property
    def session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update(
                {
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                    "User-Agent": "RentReady/1.0",
                }
            )
            self._session = s
        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # ------------------------------------------------------------------ #
    # Request helpers
    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _get(self, url: str) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(self.backoff_base * (2**attempt))
                continue

            if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                time.sleep(self.backoff_base * (2**attempt))
                continue

            resp.raise_for_status()
            return resp

        raise RuntimeError(f"Request failed after {self.max_retries} retries") from last_exc

    # ------------------------------------------------------------------ #
    # OData helpers
    # ------------------------------------------------------------------ #
    def _odata_filter(self, since: Optional[str] = None) -> str:
        if since:
            return f"ModificationTimestamp gt {since}"
        return ""

    def _build_url(
        self,
        resource: str,
        *,
        select: Optional[list[str]] = None,
        top: int = 1000,
        since: Optional[str] = None,
    ) -> str:
        params = [f"$top={top}"]
        if select:
            params.append("$select=" + ",".join(select))
        filt = self._odata_filter(since)
        if filt:
            params.append(f"$filter={filt}")
        return self._url(f"{resource}?{'&'.join(params)}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def fetch_listings(
        self,
        *,
        select: Optional[list[str]] = None,
        top: int = 1000,
        since: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch listings (Property or Listing resource) with optional
        incremental filter and automatic pagination.
        """
        url = self._build_url("Property", select=select, top=top, since=since)
        return self._paginate(url)

    def _paginate(self, url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        while url:
            resp = self._get(url)
            body = resp.json()
            results.extend(body.get("value", []))
            url = body.get("@odata.nextLink", "")
            # Defensive: some servers return an absolute vs relative link.
            if url and not urlparse(url).netloc:
                url = self._url(url)
        return results
