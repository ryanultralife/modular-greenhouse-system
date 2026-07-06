"""Login endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import ADMIN_USER, authenticate, create_token, live_permissions, require_staff
from ..db import session_dependency

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = ADMIN_USER
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str


@router.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(session_dependency)):
    role = authenticate(db, req.username, req.password)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"token": create_token(req.username, role), "username": req.username, "role": role}


@router.get("/auth/me")
def me(principal: dict = Depends(require_staff), db: Session = Depends(session_dependency)):
    return {
        "username": principal["sub"],
        "role": principal["role"],
        # Live grants (owner = all areas). The admin UI shows/hides tabs off this.
        "permissions": live_permissions(db, principal),
    }
