"""Guided walkthroughs — role-aware. Staff and owner both see it (content is
filtered by role inside the helper)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import require_staff
from ..walkthrough_content import overview_for_role

router = APIRouter(prefix="/walkthrough", tags=["walkthrough"])


@router.get("")
def walkthrough(principal: dict = Depends(require_staff)):
    return overview_for_role(principal.get("role", "staff"))
