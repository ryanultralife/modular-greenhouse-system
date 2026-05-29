"""Owner-only management of staff accounts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import ADMIN_USER, hash_password
from ..db import session_dependency
from ..models_db import User

router = APIRouter(tags=["users"])


class StaffCreate(BaseModel):
    username: str
    password: str


class StaffUpdate(BaseModel):
    password: str | None = None
    active: bool | None = None


def _out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "active": u.active, "created_at": u.created_at}


@router.get("/staff")
def list_staff(db: Session = Depends(session_dependency)):
    return [_out(u) for u in db.scalars(select(User).order_by(User.username)).all()]


@router.post("/staff", status_code=201)
def create_staff(req: StaffCreate, db: Session = Depends(session_dependency)):
    username = req.username.strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    if username == ADMIN_USER:
        raise HTTPException(status_code=400, detail=f"'{ADMIN_USER}' is reserved for the owner.")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="That username already exists.")
    # The staff table only ever mints staff; the owner is the env-password account.
    user = User(username=username, password_hash=hash_password(req.password), role="staff")
    db.add(user)
    db.commit()
    return _out(user)


@router.patch("/staff/{user_id}")
def update_staff(user_id: int, req: StaffUpdate, db: Session = Depends(session_dependency)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Staff user not found.")
    if req.password is not None:
        if not req.password:
            raise HTTPException(status_code=400, detail="Password cannot be empty.")
        user.password_hash = hash_password(req.password)
    if req.active is not None:
        user.active = req.active
    db.commit()
    return _out(user)


@router.delete("/staff/{user_id}", status_code=204)
def delete_staff(user_id: int, db: Session = Depends(session_dependency)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Staff user not found.")
    db.delete(user)
    db.commit()
