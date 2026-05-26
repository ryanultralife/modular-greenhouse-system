"""Supported integration providers and their connection tests.

Each provider declares the credential fields the admin UI should render (so Josh
adds keys without a developer) and a ``test`` function that performs a
read-only, authenticated call against the provider's own API to confirm the
keys work. No provider call here ever moves money or mutates remote state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx

TIMEOUT = 10.0


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    secret: bool = False


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    fields: tuple[Field, ...]
    test: Callable[[dict[str, str]], tuple[bool | None, str]]
    docs_url: str = ""


def _stripe_test(creds: dict[str, str]) -> tuple[bool | None, str]:
    key = creds.get("secret_key", "")
    if not key:
        return False, "Missing secret_key."
    try:
        r = httpx.get(
            "https://api.stripe.com/v1/balance",
            auth=(key, ""),
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Network error contacting Stripe: {exc}"
    if r.status_code == 200:
        return True, "Stripe key valid (read /v1/balance)."
    if r.status_code in (401, 403):
        return False, "Stripe rejected the key (unauthorized)."
    return False, f"Stripe returned HTTP {r.status_code}."


def _calendly_test(creds: dict[str, str]) -> tuple[bool | None, str]:
    token = creds.get("access_token", "")
    if not token:
        return False, "Missing access_token."
    try:
        r = httpx.get(
            "https://api.calendly.com/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Network error contacting Calendly: {exc}"
    if r.status_code == 200:
        return True, "Calendly token valid (read /users/me)."
    if r.status_code in (401, 403):
        return False, "Calendly rejected the token (unauthorized)."
    return False, f"Calendly returned HTTP {r.status_code}."


def _quickbooks_test(creds: dict[str, str]) -> tuple[bool | None, str]:
    # QuickBooks Online uses OAuth2. If a refresh token + client creds are
    # present we attempt a token refresh (read-only auth check); otherwise we
    # store the credentials but cannot validate them without the OAuth flow.
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    refresh_token = creds.get("refresh_token", "")
    if not (client_id and client_secret and refresh_token):
        return None, (
            "Stored. QuickBooks uses OAuth2 — full validation requires completing "
            "the OAuth connect flow (client_id + client_secret + refresh_token)."
        )
    try:
        r = httpx.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            auth=(client_id, client_secret),
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Network error contacting QuickBooks: {exc}"
    if r.status_code == 200:
        return True, "QuickBooks OAuth refresh succeeded."
    return False, f"QuickBooks token refresh failed (HTTP {r.status_code})."


def _smtp_test(creds: dict[str, str]) -> tuple[bool | None, str]:
    import smtplib

    host = creds.get("host", "")
    if not host:
        return False, "Missing host."
    port = int(creds.get("port") or 587)
    use_tls = str(creds.get("use_tls", "true")).strip().lower() not in ("false", "0", "no", "")
    try:
        with smtplib.SMTP(host, port, timeout=10) as s:
            if use_tls:
                s.starttls()
            if creds.get("username"):
                s.login(creds["username"], creds.get("password", ""))
    except (smtplib.SMTPException, OSError) as exc:
        return False, f"SMTP test failed: {exc}"
    return True, "SMTP connection and login OK."


def _custom_test(creds: dict[str, str]) -> tuple[bool | None, str]:
    base_url = creds.get("base_url", "")
    if not base_url:
        return None, "Stored. No base_url provided, so no connection test was run."
    api_key = creds.get("api_key", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        r = httpx.get(base_url, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        return False, f"Network error contacting {base_url}: {exc}"
    ok = r.status_code < 400
    return ok, f"{base_url} returned HTTP {r.status_code}."


PROVIDERS: dict[str, Provider] = {
    "stripe": Provider(
        "stripe",
        "Stripe (payments)",
        (Field("secret_key", "Secret key (sk_live_… / sk_test_…)", secret=True),),
        _stripe_test,
        "https://dashboard.stripe.com/apikeys",
    ),
    "calendly": Provider(
        "calendly",
        "Calendly (scheduling)",
        (
            Field("access_token", "Personal access token", secret=True),
            Field("event_type_uri", "Install event type URI (optional)"),
        ),
        _calendly_test,
        "https://calendly.com/integrations/api_webhooks",
    ),
    "quickbooks": Provider(
        "quickbooks",
        "QuickBooks Online (accounting)",
        (
            Field("client_id", "Client ID"),
            Field("client_secret", "Client secret", secret=True),
            Field("realm_id", "Company / Realm ID"),
            Field("refresh_token", "Refresh token", secret=True),
            Field("environment", "Environment (production / sandbox)"),
            Field("item_ref", "Default item id for invoice lines (optional)"),
        ),
        _quickbooks_test,
        "https://developer.intuit.com",
    ),
    "smtp": Provider(
        "smtp",
        "Email (SMTP)",
        (
            Field("host", "SMTP host (e.g. smtp.sendgrid.net)"),
            Field("port", "Port (default 587)"),
            Field("username", "Username"),
            Field("password", "Password / API key", secret=True),
            Field("from_email", "From address"),
            Field("use_tls", "Use STARTTLS (true/false)"),
        ),
        _smtp_test,
    ),
    "custom": Provider(
        "custom",
        "Custom API key",
        (
            Field("base_url", "Base URL to test (optional)"),
            Field("api_key", "API key", secret=True),
        ),
        _custom_test,
    ),
}


def provider_catalog() -> list[dict]:
    """Serializable provider list for the UI to render credential forms."""
    out = []
    for p in PROVIDERS.values():
        out.append(
            {
                "key": p.key,
                "label": p.label,
                "docs_url": p.docs_url,
                "fields": [
                    {"name": f.name, "label": f.label, "secret": f.secret}
                    for f in p.fields
                ],
            }
        )
    return out


def test_connection(provider_key: str, creds: dict[str, str]) -> tuple[bool | None, str]:
    provider = PROVIDERS.get(provider_key)
    if provider is None:
        return False, f"Unknown provider '{provider_key}'."
    return provider.test(creds)
