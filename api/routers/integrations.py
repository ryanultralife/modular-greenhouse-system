"""Self-serve integration management: Josh adds API keys without a developer.

Credentials are encrypted at rest (see api/security.py). Responses only ever
return masked values, never the raw secret.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import security
from ..db import session_dependency
from ..integrations_providers import PROVIDERS, provider_catalog, test_connection
from ..models_db import Integration
from ..schemas import IntegrationCreate, IntegrationOut, IntegrationTestResult

router = APIRouter(tags=["integrations"])


def _masked(integration: Integration) -> dict[str, str]:
    creds = security.decrypt_dict(integration.secret_blob)
    provider = PROVIDERS.get(integration.provider)
    # Mask by default: only fields the provider explicitly declares as
    # NON-secret are returned in clear. Anything else (undeclared keys, unknown
    # providers) is masked, so a mistyped/extra secret never echoes back.
    plain_fields = {f.name for f in provider.fields if not f.secret} if provider else set()
    return {
        name: (value if name in plain_fields else security.mask_value(value))
        for name, value in creds.items()
    }


def _to_out(integration: Integration) -> dict:
    return {
        "id": integration.id,
        "provider": integration.provider,
        "label": integration.label,
        "enabled": integration.enabled,
        "field_names": integration.field_names,
        "masked": _masked(integration),
        "last_test_at": integration.last_test_at,
        "last_test_ok": integration.last_test_ok,
        "last_test_message": integration.last_test_message,
    }


@router.get("/integrations/providers")
def list_providers():
    return provider_catalog()


@router.get("/integrations", response_model=list[IntegrationOut])
def list_integrations(db: Session = Depends(session_dependency)):
    stmt = select(Integration).order_by(Integration.provider)
    return [_to_out(i) for i in db.scalars(stmt).all()]


@router.post("/integrations", response_model=IntegrationOut, status_code=201)
def upsert_integration(req: IntegrationCreate, db: Session = Depends(session_dependency)):
    if req.provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider. Supported: {', '.join(PROVIDERS)}",
        )
    if not req.credentials:
        raise HTTPException(status_code=400, detail="No credentials supplied.")

    # One stored integration per provider; updating replaces credentials.
    existing = db.scalar(select(Integration).where(Integration.provider == req.provider))
    blob = security.encrypt_dict(req.credentials)
    field_names = list(req.credentials.keys())

    if existing is None:
        integration = Integration(
            provider=req.provider,
            label=req.label or PROVIDERS[req.provider].label,
            secret_blob=blob,
            field_names=field_names,
        )
        db.add(integration)
    else:
        existing.label = req.label or existing.label
        existing.secret_blob = blob
        existing.field_names = field_names
        integration = existing

    db.commit()
    return _to_out(integration)


@router.delete("/integrations/{integration_id}", status_code=204)
def delete_integration(integration_id: int, db: Session = Depends(session_dependency)):
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    db.delete(integration)
    db.commit()


@router.post("/integrations/{integration_id}/test", response_model=IntegrationTestResult)
def test_integration(integration_id: int, db: Session = Depends(session_dependency)):
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    creds = security.decrypt_dict(integration.secret_blob)
    ok, message = test_connection(integration.provider, creds)

    integration.last_test_at = datetime.now(timezone.utc)
    integration.last_test_ok = ok
    integration.last_test_message = message[:400]
    db.commit()
    return {"ok": ok, "message": message}
