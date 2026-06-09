"""Token-protected cron endpoint for Vercel Cron (or any scheduler).

Vercel Cron is configured in vercel.json to hit this on a schedule with the
Authorization header set to "Bearer $CRON_SECRET". We compare in constant time.
"""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..automations import run_automations
from ..db import session_dependency

router = APIRouter(tags=["cron"])


def _verify_cron(authorization: str | None) -> None:
    expected = os.environ.get("CRON_SECRET") or os.environ.get("MGS_AUTOMATION_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured.")
    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="Invalid cron credentials.")


@router.get("/cron/automations")
def cron_automations(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(session_dependency),
):
    _verify_cron(authorization)
    return {"results": run_automations(db, actor="system:cron")}
