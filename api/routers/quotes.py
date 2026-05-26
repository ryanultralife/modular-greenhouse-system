"""Live configurator: configure a build and get BOM + quote + engineering."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from greenhouse import Catalog, CatalogError
from greenhouse.models import SHAPE_RUN_COUNTS

from .. import catalog_store
from ..db import session_dependency
from ..engine_bridge import compute_quote
from ..schemas import QuoteRequest, QuoteResponse

router = APIRouter(tags=["configurator"])


@router.get("/models")
def list_models(db: Session = Depends(session_dependency)):
    catalog = Catalog(catalog_store.load(db))
    models = [
        {
            "id": mid,
            "name": catalog.model(mid)["name"],
            "width_ft": catalog.model(mid)["width_ft"],
            "bay_length_ft": catalog.model(mid)["bay_length_ft"],
        }
        for mid in catalog.model_ids()
    ]
    return {
        "company": catalog.company,
        "models": models,
        "shapes": [{"name": s, "runs": n} for s, n in SHAPE_RUN_COUNTS.items()],
    }


@router.post("/quote", response_model=QuoteResponse)
def make_quote(req: QuoteRequest, db: Session = Depends(session_dependency)):
    try:
        return compute_quote(catalog_store.load(db), req.model, req.shape, req.runs)
    except (CatalogError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
