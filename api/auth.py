"""Authentication and roles.

Two roles:
  * owner — full access (secrets, pricing, integrations). Authenticates with
    MGS_ADMIN_PASSWORD (or a generated, git-ignored file) as user "admin".
  * staff — operational access only (work board, inventory, production,
    shipping). Staff are DB accounts the owner creates; passwords are stored
    salted+hashed (PBKDF2, stdlib — no new dependency).

Login issues a Fernet-encrypted bearer token carrying the username + role with
an expiry. Public endpoints (/api/public/*), /health, login, and the static UI
are not protected.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import stat
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import security
from .db import session_dependency
from .models_db import ROLES, STAFF_PERMISSIONS, User

PW_FILE = security.DATA_DIR / ".admin_password"
ADMIN_USER = os.environ.get("MGS_ADMIN_USER", "admin")
TOKEN_TTL_SECONDS = int(os.environ.get("MGS_TOKEN_TTL", str(12 * 3600)))

PBKDF2_ROUNDS = 200_000


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _forbidden(detail: str = "Owner access required") -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


# ---- password hashing (staff accounts) ----
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(dk.hex(), dk_hex)


# ---- owner password (env / generated file) ----
def _resolve_owner_password() -> str:
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
        raise RuntimeError(
            "MGS_ADMIN_PASSWORD is not set and a password file could not be "
            "written. Set the MGS_ADMIN_PASSWORD environment variable."
        ) from exc
    print(f"[auth] No MGS_ADMIN_PASSWORD set. Generated owner password for '{ADMIN_USER}': {pw}")
    print(f"[auth] Stored at {PW_FILE} (git-ignored). Set MGS_ADMIN_PASSWORD to override.")
    return pw


def authenticate(db: Session, username: str, password: str) -> str | None:
    """Return the role on success, else None."""
    if secrets.compare_digest(username or "", ADMIN_USER) and secrets.compare_digest(
        password or "", _resolve_owner_password()
    ):
        return "owner"
    user = db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    if user and verify_password(password or "", user.password_hash):
        return user.role
    return None


# ---- tokens ----
def create_token(username: str, role: str) -> str:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    return security.encrypt_dict(payload)


def _principal(creds: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False))) -> dict:
    if creds is None or not creds.credentials:
        raise _unauthorized()
    try:
        payload = security.decrypt_dict(creds.credentials)
    except ValueError as exc:
        raise _unauthorized("Invalid token") from exc
    try:
        expired = int(payload.get("exp", 0)) < int(time.time())
    except (TypeError, ValueError):
        expired = True  # malformed/missing expiry -> treat as expired, not a 500
    if expired:
        raise _unauthorized("Session expired")
    role = payload.get("role")
    if role not in ROLES:
        # Token predates roles (or is malformed) — force a fresh login rather
        # than guessing a role (guessing "staff" locks owners out with a 403;
        # guessing "owner" would over-grant).
        raise _unauthorized("Please sign in again")
    return {"sub": payload.get("sub", ""), "role": role}


def require_staff(principal: dict = Depends(_principal)) -> dict:
    """Any authenticated user (owner or staff)."""
    return principal


def require_owner(principal: dict = Depends(_principal)) -> dict:
    if principal.get("role") != "owner":
        raise _forbidden()
    return principal


def live_permissions(db: Session, principal: dict) -> list[str]:
    """The areas this principal can use RIGHT NOW. Owners get everything;
    staff get whatever the owner has granted, read fresh from the DB (not the
    token) so a revoke or account-disable applies to the very next request."""
    if principal.get("role") == "owner":
        return list(STAFF_PERMISSIONS)
    user = db.scalar(select(User).where(User.username == principal.get("sub"), User.active.is_(True)))
    if user is None:
        return []
    return [p for p in (user.permissions or []) if p in STAFF_PERMISSIONS]


def require_permission(area: str):
    """Dependency factory: owner always passes; staff pass only if the owner
    granted them this area on the Staff tab."""
    if area not in STAFF_PERMISSIONS:  # catch wiring typos at import time
        raise ValueError(f"Unknown permission area: {area}")

    # The principal comes via require_staff (a passthrough of _principal) so a
    # test-time override of require_staff applies here too.
    def dep(
        principal: dict = Depends(require_staff),
        db: Session = Depends(session_dependency),
    ) -> dict:
        if principal.get("role") == "owner":
            return principal
        if area in live_permissions(db, principal):
            return principal
        raise _forbidden("You don't have access to this area. Ask the owner to grant it on the Staff tab.")

    return dep
