"""Owner-only marketing automation controls."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..automations import _ensure_seeded, run_automations
from ..db import session_dependency
from ..models_db import AUTOMATION_KINDS, AuditEvent, Automation

router = APIRouter(tags=["automations"])


class AutomationUpdate(BaseModel):
    enabled: bool | None = None
    config: dict | None = None


def _out(a: Automation) -> dict:
    return {
        "kind": a.kind,
        "enabled": a.enabled,
        "config": a.config or {},
        "last_run_at": a.last_run_at,
        "last_run_ok": a.last_run_ok,
        "last_run_message": a.last_run_message,
    }


@router.get("/automations")
def list_automations(db: Session = Depends(session_dependency)):
    _ensure_seeded(db)
    return [_out(db.get(Automation, k)) for k in AUTOMATION_KINDS]


@router.patch("/automations/{kind}")
def update_automation(kind: str, req: AutomationUpdate, db: Session = Depends(session_dependency)):
    if kind not in AUTOMATION_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown automation '{kind}'.")
    _ensure_seeded(db)
    a = db.get(Automation, kind)
    if req.enabled is not None:
        a.enabled = req.enabled
    if req.config is not None:
        a.config = {**(a.config or {}), **req.config}
    db.commit()
    return _out(a)


@router.post("/automations/run")
def run_all(
    kind: str | None = None,
    principal: dict = Depends(lambda: None),  # placeholder; owner-only via router dep
    db: Session = Depends(session_dependency),
):
    if kind and kind not in AUTOMATION_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown automation '{kind}'.")
    return {"results": run_automations(db, only_kind=kind, actor="human:owner")}


@router.get("/automations/events")
def recent_events(limit: int = 50, db: Session = Depends(session_dependency)):
    rows = db.scalars(select(AuditEvent).order_by(desc(AuditEvent.id)).limit(min(limit, 200))).all()
    return [
        {"id": r.id, "occurred_at": r.occurred_at, "actor": r.actor, "kind": r.kind,
         "entity_type": r.entity_type, "entity_id": r.entity_id, "data": r.data or {}}
        for r in rows
    ]
