"""In-app onboarding and reference. Accessible to staff and owner — content is
filtered by role inside the helper."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_staff
from ..db import session_dependency
from ..help_content import overview_for_role

router = APIRouter(prefix="/help", tags=["help"])


@router.get("/overview")
def overview(principal: dict = Depends(require_staff), db: Session = Depends(session_dependency)):
    return overview_for_role(db, principal.get("role", "staff"))
