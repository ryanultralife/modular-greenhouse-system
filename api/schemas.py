"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


# ---- Quotes / configurator ----
class QuoteRequest(BaseModel):
    model: str
    shape: str
    runs: list[float] = Field(min_length=1)


class BomLineOut(BaseModel):
    sku_id: str
    name: str
    quantity: int


class QuoteLineOut(BaseModel):
    sku_id: str
    name: str
    quantity: int
    unit_price_usd: float | None
    verified_price: bool
    extended_usd: float | None


class EngineeringOut(BaseModel):
    status: str
    reasons: list[str]
    requires_signoff: bool
    used_placeholder_limits: bool
    disclaimer: str


class QuoteResponse(BaseModel):
    model_id: str
    model_name: str
    shape: str
    runs: list[float]
    total_bays: int
    footprint_sqft: float
    bom: list[BomLineOut]
    quote_lines: list[QuoteLineOut]
    verified_subtotal_usd: float
    quote_complete: bool
    engineering: EngineeringOut


# ---- Orders ----
class OrderCreate(QuoteRequest):
    customer_name: str = ""
    customer_email: str = ""


class OrderStatusUpdate(BaseModel):
    status: str | None = None
    fab_session_id: int | None = None


class OrderOut(BaseModel):
    id: int
    created_at: datetime
    customer_name: str
    customer_email: str
    model_id: str
    shape: str
    runs: list[float]
    status: str
    bom: list[dict]
    pricing: dict
    engineering: dict
    fab_session_id: int | None


# ---- Catalog editing ----
class SkuUpdate(BaseModel):
    price_usd: float | None = None
    verified_price: bool | None = None
    weight_lb: float | None = None
    fulfillment: str | None = None  # "in_house" | "copacker"
    copacker: str | None = None


class LimitUpdate(BaseModel):
    value: float | int | list | None
    verified: bool = False


# ---- Fabrication sessions ----
class FabSessionCreate(BaseModel):
    week_of: date
    label: str = ""


class FabSessionAssign(BaseModel):
    order_ids: list[int]


class FabSessionOut(BaseModel):
    id: int
    week_of: date
    label: str
    status: str
    order_ids: list[int]


# ---- Integrations ----
class IntegrationCreate(BaseModel):
    provider: str
    label: str = ""
    credentials: dict[str, str]


class IntegrationOut(BaseModel):
    id: int
    provider: str
    label: str
    enabled: bool
    field_names: list[str]
    masked: dict[str, str]
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str


class IntegrationTestResult(BaseModel):
    ok: bool | None
    message: str
