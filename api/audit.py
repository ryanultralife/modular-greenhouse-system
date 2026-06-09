"""Append-only event log + helpers.

Every business moment that matters (lead created, checkout started, order paid,
order shipped, automation fired) gets a row. This serves three purposes:

  1. An audit trail for the owner — who/what changed and when.
  2. A foundation for an agentic future — actor field distinguishes humans,
     the system, and (eventually) agents.
  3. The natural queue for marketing automations: each automation marks the
     work it has done by recording a "marketing.<kind>.sent" event, so a
     re-run of the dispatcher naturally skips orders it has already touched.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models_db import AuditEvent


def record_event(
    db: Session,
    kind: str,
    *,
    entity_type: str = "",
    entity_id: int | None = None,
    actor: str = "system",
    data: dict | None = None,
    commit: bool = True,
) -> AuditEvent:
    event = AuditEvent(
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        data=data or {},
    )
    db.add(event)
    if commit:
        db.commit()
    return event


def has_event(db: Session, *, kind: str, entity_id: int) -> bool:
    """Idempotency check: has this exact (kind, entity_id) been recorded?"""
    return db.scalar(
        select(AuditEvent.id).where(AuditEvent.kind == kind, AuditEvent.entity_id == entity_id).limit(1)
    ) is not None
