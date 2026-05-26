"""Admin editing of the catalog: SKU prices/weights/fulfillment and limits.

Edits are stored as overrides in the database (serverless-safe), merged over
the bundled seed catalog at read time.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import catalog_store
from ..db import session_dependency
from ..schemas import LimitUpdate, SkuUpdate

router = APIRouter(tags=["catalog"])


@router.get("/catalog")
def get_catalog(db: Session = Depends(session_dependency)):
    return catalog_store.load(db)


@router.put("/catalog/models/{model_id}/skus/{sku_id}")
def put_sku(model_id: str, sku_id: str, req: SkuUpdate, db: Session = Depends(session_dependency)):
    fields = req.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    if "fulfillment" in fields and fields["fulfillment"] not in ("in_house", "copacker"):
        raise HTTPException(
            status_code=400, detail="fulfillment must be 'in_house' or 'copacker'."
        )
    try:
        return catalog_store.update_sku(db, model_id, sku_id, fields)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/catalog/limits/{key}")
def put_limit(key: str, req: LimitUpdate, db: Session = Depends(session_dependency)):
    try:
        return catalog_store.update_limit(db, key, req.value, req.verified)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
