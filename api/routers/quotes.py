"""Live configurator: configure a build and get BOM + quote + engineering."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from greenhouse import Catalog, CatalogError
from greenhouse.models import SHAPE_RUN_COUNTS

from ..engine_bridge import compute_quote
from ..schemas import QuoteRequest, QuoteResponse

router = APIRouter(tags=["configurator"])


@router.get("/models")
def list_models():
    catalog = Catalog.load()
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
def make_quote(req: QuoteRequest):
    try:
        return compute_quote(req.model, req.shape, req.runs)
    except (CatalogError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
