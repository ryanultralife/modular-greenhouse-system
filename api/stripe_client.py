"""Minimal Stripe REST client for invoicing.

Only the handful of endpoints we need, form-encoded as Stripe expects. The
HTTP client is injectable so tests can drive it with httpx.MockTransport and
never touch the network.
"""

from __future__ import annotations

import httpx

STRIPE_BASE = "https://api.stripe.com"


class StripeError(Exception):
    pass


class StripeClient:
    def __init__(self, api_key: str = "", http_client: httpx.Client | None = None, timeout: float = 20.0):
        self._owns = http_client is None
        self._client = http_client or httpx.Client(
            base_url=STRIPE_BASE, auth=(api_key, ""), timeout=timeout
        )

    def _post(self, path: str, data: dict) -> dict:
        try:
            r = self._client.post(path, data=data)
        except httpx.HTTPError as exc:
            raise StripeError(f"Network error calling Stripe {path}: {exc}") from exc
        if r.status_code >= 400:
            raise StripeError(f"Stripe {path} failed: HTTP {r.status_code} {r.text[:300]}")
        return r.json()

    def create_customer(self, email: str | None, name: str | None) -> dict:
        data: dict = {}
        if email:
            data["email"] = email
        if name:
            data["name"] = name
        return self._post("/v1/customers", data)

    def create_invoice_item(
        self, customer: str, unit_amount_cents: int, quantity: int, currency: str, description: str
    ) -> dict:
        return self._post(
            "/v1/invoiceitems",
            {
                "customer": customer,
                "unit_amount": unit_amount_cents,
                "quantity": quantity,
                "currency": currency,
                "description": description,
            },
        )

    def create_invoice(self, customer: str, days_until_due: int = 30) -> dict:
        return self._post(
            "/v1/invoices",
            {
                "customer": customer,
                "collection_method": "send_invoice",
                "days_until_due": days_until_due,
                "auto_advance": "false",
            },
        )

    def finalize_invoice(self, invoice_id: str) -> dict:
        return self._post(f"/v1/invoices/{invoice_id}/finalize", {})

    def send_invoice(self, invoice_id: str) -> dict:
        return self._post(f"/v1/invoices/{invoice_id}/send", {})

    def close(self) -> None:
        if self._owns:
            self._client.close()
