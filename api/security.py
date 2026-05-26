"""Encryption for integration secrets (Stripe/QuickBooks/etc. API keys).

Keys are encrypted at rest with Fernet (AES-128-CBC + HMAC). The master key
comes from:

  1. env var ``MGS_SECRET_KEY`` (preferred for real deployments), or
  2. a local file ``data/.secret_key`` that is generated on first run.

The local key file and the SQLite DB are git-ignored, so secrets never land in
the repo. Secret values are never logged and are masked in API responses.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
KEY_FILE = DATA_DIR / ".secret_key"

_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("MGS_SECRET_KEY")
    if env_key:
        return env_key.encode()

    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    try:
        KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    return key


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_dict(data: dict[str, Any]) -> str:
    token = get_fernet().encrypt(json.dumps(data).encode())
    return token.decode()


def decrypt_dict(token: str) -> dict[str, Any]:
    try:
        raw = get_fernet().decrypt(token.encode())
    except InvalidToken as exc:
        raise ValueError(
            "Could not decrypt stored credentials. The master key (MGS_SECRET_KEY "
            "or data/.secret_key) does not match the one used to encrypt them."
        ) from exc
    return json.loads(raw.decode())


def mask_value(value: str) -> str:
    """Mask a secret for display: keep the last 4 characters only."""
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]
