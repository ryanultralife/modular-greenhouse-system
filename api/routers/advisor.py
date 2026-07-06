"""Public AI advisor endpoint (open — abuse-limited inside the service)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..advisor import AdvisorError, run_advisor
from ..db import session_dependency
from .public import _clean_attribution

router = APIRouter(prefix="/public", tags=["advisor"])


class AdvisorRequest(BaseModel):
    messages: list[dict] = Field(min_length=1, max_length=40)
    attribution: dict | None = None


class AdvisorResponse(BaseModel):
    reply: str
    lead_captured: bool


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


@router.post("/advisor", response_model=AdvisorResponse)
def advisor(req: AdvisorRequest, request: Request, db: Session = Depends(session_dependency)):
    try:
        return run_advisor(
            db,
            req.messages,
            attribution=_clean_attribution(req.attribution),
            ip=_client_ip(request),
        )
    except AdvisorError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
