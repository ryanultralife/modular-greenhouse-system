"""Admin: preset products, co-packer orders, and co-packer config."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import copacker as copacker_svc, inventory_store
from ..db import session_dependency
from ..models_db import CoPackerOrder, Preset, Setting

router = APIRouter(tags=["presets"])


class PresetIn(BaseModel):
    name: str
    description: str = ""
    model_id: str = ""
    shape: str = "straight"
    runs: list[float] = []
    price_usd: float | None = None
    compare_at_usd: float | None = None
    verified_price: bool = False
    ship_speed: str = "next_day"
    image_url: str = ""
    active: bool = True


class CoPackerConfig(BaseModel):
    name: str = ""
    email: str = ""


class CoPackerOrderIn(BaseModel):
    copacker: str = ""
    items: list[dict]
    notes: str = ""
    email_to: str | None = None


def _preset_out(p: Preset, db: Session) -> dict:
    item = inventory_store.get_item(db, p.stock_key)
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "model_id": p.model_id,
        "shape": p.shape,
        "runs": p.runs,
        "price_usd": p.price_usd,
        "compare_at_usd": p.compare_at_usd,
        "verified_price": p.verified_price,
        "ship_speed": p.ship_speed,
        "image_url": p.image_url,
        "active": p.active,
        "on_hand": item.on_hand if item else 0,
    }


@router.get("/presets")
def list_presets(db: Session = Depends(session_dependency)):
    return [_preset_out(p, db) for p in db.scalars(select(Preset).order_by(Preset.name)).all()]


@router.post("/presets", status_code=201)
def create_preset(req: PresetIn, db: Session = Depends(session_dependency)):
    p = Preset(**req.model_dump())
    db.add(p)
    db.commit()
    # Ensure a finished-unit inventory row exists for stock tracking.
    inventory_store.upsert_item(db, kind="finished_unit", key=p.stock_key, name=p.name, on_hand=0)
    return _preset_out(p, db)


@router.put("/presets/{preset_id}")
def update_preset(preset_id: int, req: PresetIn, db: Session = Depends(session_dependency)):
    p = db.get(Preset, preset_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    for k, v in req.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return _preset_out(p, db)


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(preset_id: int, db: Session = Depends(session_dependency)):
    p = db.get(Preset, preset_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    db.delete(p)
    db.commit()


# ---- co-packer config + orders ----
@router.get("/copacker/config")
def get_copacker_config(db: Session = Depends(session_dependency)):
    row = db.get(Setting, "copacker_config")
    return row.value if row and row.value else {"name": "", "email": ""}


@router.put("/copacker/config")
def set_copacker_config(req: CoPackerConfig, db: Session = Depends(session_dependency)):
    row = db.get(Setting, "copacker_config")
    if row is None:
        db.add(Setting(key="copacker_config", value=req.model_dump()))
    else:
        row.value = req.model_dump()
    db.commit()
    return req.model_dump()


@router.get("/copacker/orders")
def list_copacker_orders(db: Session = Depends(session_dependency)):
    rows = db.scalars(select(CoPackerOrder).order_by(CoPackerOrder.created_at.desc())).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "copacker": r.copacker,
            "items": r.items,
            "status": r.status,
            "trigger": r.trigger,
            "related_order_id": r.related_order_id,
            "emailed": r.emailed,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/copacker/orders", status_code=201)
def create_copacker_order(req: CoPackerOrderIn, db: Session = Depends(session_dependency)):
    order = copacker_svc.create_copacker_order(
        db,
        copacker=req.copacker,
        items=req.items,
        trigger="manual",
        notes=req.notes,
        email_to=req.email_to,
    )
    return {"id": order.id, "status": order.status, "emailed": order.emailed}
