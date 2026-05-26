"""Minimal QuickBooks Online client (OAuth2 + Customer/Invoice).

Only what we need for accounting sync. The HTTP client is injectable so tests
drive it with httpx.MockTransport and never hit the network. The OAuth token
endpoint and the API live on different hosts; both go through the same client
using absolute vs. base-relative URLs.
"""

from __future__ import annotations

import httpx

OAUTH_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
ENV_BASE = {
    "production": "https://quickbooks.api.intuit.com",
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
}
MINOR_VERSION = "65"


class QuickBooksError(Exception):
    pass


def _q_escape(value: str) -> str:
    return value.replace("'", "''")


class QuickBooksClient:
    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        realm_id: str = "",
        environment: str = "production",
        access_token: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 20.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.realm_id = realm_id
        self.environment = environment if environment in ENV_BASE else "production"
        self._access_token = access_token
        self._owns = http_client is None
        self._client = http_client or httpx.Client(base_url=ENV_BASE[self.environment], timeout=timeout)

    # ---- auth ----
    def refresh_access_token(self) -> str:
        try:
            r = self._client.post(
                OAUTH_TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise QuickBooksError(f"Network error refreshing QuickBooks token: {exc}") from exc
        if r.status_code >= 400:
            raise QuickBooksError(f"QuickBooks token refresh failed: HTTP {r.status_code} {r.text[:200]}")
        tok = r.json()
        self._access_token = tok["access_token"]
        if tok.get("refresh_token"):
            self.refresh_token = tok["refresh_token"]
        return self._access_token

    def _headers(self) -> dict:
        if not self._access_token:
            self.refresh_access_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ---- low-level api ----
    def _api(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> dict:
        p = {"minorversion": MINOR_VERSION}
        if params:
            p.update(params)
        url = f"/v3/company/{self.realm_id}{path}"
        try:
            r = self._client.request(method, url, params=p, json=json, headers=self._headers())
        except httpx.HTTPError as exc:
            raise QuickBooksError(f"Network error calling QuickBooks {path}: {exc}") from exc
        if r.status_code >= 400:
            raise QuickBooksError(f"QuickBooks {path} failed: HTTP {r.status_code} {r.text[:300]}")
        return r.json()

    def query(self, statement: str) -> dict:
        return self._api("GET", "/query", params={"query": statement})

    # ---- domain ----
    def find_customer(self, display_name: str) -> dict | None:
        data = self.query(f"select * from Customer where DisplayName = '{_q_escape(display_name)}'")
        rows = data.get("QueryResponse", {}).get("Customer") or []
        return rows[0] if rows else None

    def create_customer(self, display_name: str, email: str | None) -> dict:
        body: dict = {"DisplayName": display_name}
        if email:
            body["PrimaryEmailAddr"] = {"Address": email}
        return self._api("POST", "/customer", json=body)["Customer"]

    def first_item_ref(self) -> str | None:
        data = self.query("select * from Item maxresults 1")
        items = data.get("QueryResponse", {}).get("Item") or []
        return items[0]["Id"] if items else None

    def create_invoice(self, customer_id: str, lines: list[dict], item_ref: str) -> dict:
        line_items = [
            {
                "Amount": round(line["amount"], 2),
                "DetailType": "SalesItemLineDetail",
                "Description": line.get("description", "item"),
                "SalesItemLineDetail": {
                    "ItemRef": {"value": item_ref},
                    "Qty": line["qty"],
                    "UnitPrice": line["unit_price"],
                },
            }
            for line in lines
        ]
        body = {"CustomerRef": {"value": customer_id}, "Line": line_items}
        return self._api("POST", "/invoice", json=body)["Invoice"]

    def close(self) -> None:
        if self._owns:
            self._client.close()
