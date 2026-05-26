"""Admin authentication.

Single-admin model suited to a small business: a username (default "admin")
and a password. The password comes from MGS_ADMIN_PASSWORD, or — if unset — a
random one generated on first run and stored in a git-ignored file (logged
once so Josh can read it). Login issues a Fernet-encrypted bearer token
(tamper-proof, with an expiry); admin endpoints require it.

Public endpoints (/api/public/*), /health, and the static UI are NOT protected.
"""

from __future__ import annotations

import os
import secrets
import stat
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import security

PW_FILE = security.DATA_DIR / ".admin_password"
ADMIN_USER = os.environ.get("MGS_ADMIN_USER", "admin")
TOKEN_TTL_SECONDS = int(os.environ.get("MGS_TOKEN_TTL", str(12 * 3600)))


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _resolve_password() -> str:
    pw = os.environ.get("MGS_ADMIN_PASSWORD")
    if pw:
        return pw
    if PW_FILE.exists():
        return PW_FILE.read_text().strip()
    pw = secrets.token_urlsafe(16)
    try:
        security.DATA_DIR.mkdir(parents=True, exist_ok=True)
        PW_FILE.write_text(pw)
        PW_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError as exc:
        # Read-only filesystem (e.g. serverless): a per-instance password is
        # useless, so require an explicit one.
        raise RuntimeError(
            "MGS_ADMIN_PASSWORD is not set and a password file could not be "
            "written. Set the MGS_ADMIN_PASSWORD environment variable."
        ) from exc
    print(f"[auth] No MGS_ADMIN_PASSWORD set. Generated admin password for user '{ADMIN_USER}': {pw}")
    print(f"[auth] Stored at {PW_FILE} (git-ignored). Set MGS_ADMIN_PASSWORD to override.")
    return pw


def verify_credentials(username: str, password: str) -> bool:
    expected = _resolve_password()
    user_ok = secrets.compare_digest(username or "", ADMIN_USER)
    pw_ok = secrets.compare_digest(password or "", expected)
    return user_ok and pw_ok


def create_token(username: str) -> str:
    payload = {"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    return security.encrypt_dict(payload)


def verify_token(token: str) -> str:
    try:
        payload = security.decrypt_dict(token)
    except ValueError as exc:
        raise _unauthorized("Invalid token") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise _unauthorized("Session expired")
    return payload.get("sub", ADMIN_USER)


_bearer = HTTPBearer(auto_error=False)


def require_admin(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if creds is None or not creds.credentials:
        raise _unauthorized()
    return verify_token(creds.credentials)
