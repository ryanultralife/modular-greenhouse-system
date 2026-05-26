"""Outbound email via the configured SMTP integration.

Works with any SMTP provider (Gmail, SendGrid SMTP, Postmark, etc.) using the
stdlib smtplib — no extra dependency. The sender is injectable so tests record
messages without opening a connection.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import security
from .models_db import Integration


class EmailError(Exception):
    pass


def _truthy(value) -> bool:
    return str(value).strip().lower() not in ("false", "0", "no", "", "none")


class EmailSender:
    def __init__(self, host: str, port, username: str = "", password: str = "", use_tls=True, timeout: float = 20.0):
        self.host = host
        self.port = int(port or 587)
        self.username = username
        self.password = password
        self.use_tls = _truthy(use_tls)
        self.timeout = timeout

    def send(self, from_email: str, to: str, subject: str, html: str, text: str | None = None) -> None:
        msg = EmailMessage()
        msg["From"] = from_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text or "This message requires an HTML-capable email client.")
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as s:
                if self.use_tls:
                    s.starttls()
                if self.username:
                    s.login(self.username, self.password)
                s.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"SMTP send failed: {exc}") from exc


def _smtp_creds(db: Session) -> dict:
    integ = db.scalar(
        select(Integration).where(Integration.provider == "smtp", Integration.enabled.is_(True))
    )
    if integ is None:
        raise EmailError(
            "No enabled email (SMTP) integration is configured. Add SMTP settings "
            "under Integrations first."
        )
    creds = security.decrypt_dict(integ.secret_blob)
    if not creds.get("host") or not creds.get("from_email"):
        raise EmailError("SMTP integration needs at least 'host' and 'from_email'.")
    return creds


def send_email(
    db: Session,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    *,
    sender: EmailSender | None = None,
    from_email: str | None = None,
) -> bool:
    if not to:
        raise EmailError("No recipient email address on this order.")
    if sender is None:
        creds = _smtp_creds(db)
        sender = EmailSender(
            creds["host"], creds.get("port"), creds.get("username", ""),
            creds.get("password", ""), creds.get("use_tls", True),
        )
        from_email = creds["from_email"]
    sender.send(from_email or "no-reply@localhost", to, subject, html, text)
    return True
