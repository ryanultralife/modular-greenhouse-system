"""Minimal Calendly client (current user, event types, single-use links).

Injectable HTTP client so tests run offline via httpx.MockTransport.
"""

from __future__ import annotations

import httpx

CALENDLY_BASE = "https://api.calendly.com"


class CalendlyError(Exception):
    pass


class CalendlyClient:
    def __init__(self, token: str = "", http_client: httpx.Client | None = None, timeout: float = 20.0):
        self._owns = http_client is None
        self._client = http_client or httpx.Client(
            base_url=CALENDLY_BASE,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            r = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CalendlyError(f"Network error calling Calendly {path}: {exc}") from exc
        if r.status_code >= 400:
            raise CalendlyError(f"Calendly {path} failed: HTTP {r.status_code} {r.text[:300]}")
        return r.json()

    def me(self) -> dict:
        return self._request("GET", "/users/me")["resource"]

    def active_event_types(self, user_uri: str) -> list[dict]:
        data = self._request("GET", "/event_types", params={"user": user_uri, "active": "true"})
        return data.get("collection", [])

    def create_single_use_link(self, event_type_uri: str) -> str:
        data = self._request(
            "POST",
            "/scheduling_links",
            json={"max_event_count": 1, "owner": event_type_uri, "owner_type": "EventType"},
        )
        return data["resource"]["booking_url"]

    def close(self) -> None:
        if self._owns:
            self._client.close()
