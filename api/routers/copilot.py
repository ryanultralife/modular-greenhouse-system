"""Owner copilot endpoint (owner-only via the router group in app.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_owner
from ..copilot import CopilotError, run_copilot
from ..db import session_dependency

router = APIRouter(tags=["copilot"])


class CopilotRequest(BaseModel):
    messages: list[dict] = Field(min_length=1, max_length=40)


class CopilotResponse(BaseModel):
    reply: str


@router.post("/copilot", response_model=CopilotResponse)
def copilot(
    req: CopilotRequest,
    principal: dict = Depends(require_owner),
    db: Session = Depends(session_dependency),
):
    try:
        return run_copilot(db, req.messages, username=principal.get("sub", ""))
    except CopilotError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
