"""Login endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import ADMIN_USER, create_token, require_admin, verify_credentials

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = ADMIN_USER
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


@router.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    if not verify_credentials(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"token": create_token(req.username), "username": req.username}


@router.get("/auth/me")
def me(user: str = Depends(require_admin)):
    return {"username": user}
