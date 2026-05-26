"""Admin editing of the catalog: SKU prices/weights/fulfillment and limits."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import catalog_store
from ..schemas import LimitUpdate, SkuUpdate

router = APIRouter(tags=["catalog"])


@router.get("/catalog")
def get_catalog():
    return catalog_store.load()


@router.put("/catalog/models/{model_id}/skus/{sku_id}")
def put_sku(model_id: str, sku_id: str, req: SkuUpdate):
    fields = req.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    if "fulfillment" in fields and fields["fulfillment"] not in ("in_house", "copacker"):
        raise HTTPException(
            status_code=400, detail="fulfillment must be 'in_house' or 'copacker'."
        )
    try:
        return catalog_store.update_sku(model_id, sku_id, fields)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/catalog/limits/{key}")
def put_limit(key: str, req: LimitUpdate):
    try:
        return catalog_store.update_limit(key, req.value, req.verified)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
