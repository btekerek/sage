"""
System Configuration API  (UC-12).

GET  /api/config          — return current effective values (DB overrides + env defaults)
PATCH /api/config         — update one or more runtime config values
                            each change is also appended to the event store

Configurable keys:
  replenishment_target_days     int    > 0
  replenishment_lead_time_days  int    > 0
  costing_strategy              FIFO | WAC
  ai_confidence_threshold       float  0.0 – 1.0
  margin_target                 float  0.0 – 0.99
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.settings import get_settings
from app.infrastructure.event_store.models import StoredEvent
from app.infrastructure.projectors.read_entities import ProductReadEntity, SystemConfigEntity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

# Keys that can be changed at runtime
_ALLOWED_KEYS = {
    "replenishment_target_days",
    "replenishment_lead_time_days",
    "replenishment_weekly_budget",
    "costing_strategy",
    "ai_confidence_threshold",
    "margin_target",
}


# ── Pydantic models ────────────────────────────────────────────────────────────

class SystemConfigResponse(BaseModel):
    replenishment_target_days: int
    replenishment_lead_time_days: int
    replenishment_weekly_budget: int
    costing_strategy: str
    ai_confidence_threshold: float
    margin_target: float
    # metadata
    overrides: dict[str, str]   # which keys are overridden in DB (vs env default)


class PatchConfigRequest(BaseModel):
    replenishment_target_days: int | None = Field(None, gt=0)
    replenishment_lead_time_days: int | None = Field(None, gt=0)
    replenishment_weekly_budget: int | None = Field(None, gt=0)
    costing_strategy: str | None = None
    ai_confidence_threshold: float | None = Field(None, ge=0.0, le=1.0)
    margin_target: float | None = Field(None, ge=0.0, lt=1.0)
    updated_by: str = "system"


# ── Helper ─────────────────────────────────────────────────────────────────────

async def get_runtime_config(session: AsyncSession) -> dict:
    """
    Return the effective runtime config dict, merging DB overrides over env defaults.
    Import and call this in any route that needs live config values.
    """
    env = get_settings()
    defaults = {
        "replenishment_target_days": env.replenishment_target_days,
        "replenishment_lead_time_days": env.replenishment_lead_time_days,
        "replenishment_weekly_budget": env.replenishment_weekly_budget,
        "costing_strategy": env.costing_strategy,
        "ai_confidence_threshold": env.ai_confidence_threshold,
        "margin_target": env.margin_target,
    }

    result = await session.execute(select(SystemConfigEntity))
    rows = result.scalars().all()
    overrides = {r.key: r.value for r in rows}

    merged = dict(defaults)
    for key, raw_val in overrides.items():
        if key not in defaults:
            continue
        try:
            if key in ("ai_confidence_threshold", "margin_target"):
                merged[key] = float(raw_val)
            elif key in ("replenishment_target_days", "replenishment_lead_time_days", "replenishment_weekly_budget"):
                merged[key] = int(raw_val)
            else:
                merged[key] = raw_val
        except (ValueError, TypeError):
            pass   # bad DB value — keep env default

    merged["_overrides"] = overrides
    return merged


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=SystemConfigResponse)
async def get_config(
    session: AsyncSession = Depends(get_db_session),
) -> SystemConfigResponse:
    """Return the current effective system configuration."""
    cfg = await get_runtime_config(session)
    return SystemConfigResponse(
        replenishment_target_days=int(cfg["replenishment_target_days"]),
        replenishment_lead_time_days=int(cfg["replenishment_lead_time_days"]),
        replenishment_weekly_budget=int(cfg["replenishment_weekly_budget"]),
        costing_strategy=str(cfg["costing_strategy"]),
        ai_confidence_threshold=float(cfg["ai_confidence_threshold"]),
        margin_target=float(cfg["margin_target"]),
        overrides=cfg.get("_overrides", {}),
    )


@router.patch("", response_model=SystemConfigResponse, status_code=status.HTTP_200_OK)
async def patch_config(
    payload: PatchConfigRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SystemConfigResponse:
    """
    Update one or more runtime config values.
    Each changed key is upserted into system_config and a SystemConfigEvent
    is appended to the event store for full audit traceability.
    """
    updates: dict[str, str] = {}

    if payload.replenishment_target_days is not None:
        updates["replenishment_target_days"] = str(payload.replenishment_target_days)
    if payload.replenishment_lead_time_days is not None:
        updates["replenishment_lead_time_days"] = str(payload.replenishment_lead_time_days)
    if payload.replenishment_weekly_budget is not None:
        updates["replenishment_weekly_budget"] = str(payload.replenishment_weekly_budget)
    if payload.costing_strategy is not None:
        val = payload.costing_strategy.strip().upper()
        if val not in ("FIFO", "WAC"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="costing_strategy must be FIFO or WAC",
            )
        updates["costing_strategy"] = val
    if payload.ai_confidence_threshold is not None:
        updates["ai_confidence_threshold"] = str(payload.ai_confidence_threshold)
    if payload.margin_target is not None:
        updates["margin_target"] = str(payload.margin_target)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid fields to update",
        )

    now = datetime.now(timezone.utc)

    # Fetch previous values for the event payload
    prev_cfg = await get_runtime_config(session)

    for key, new_val in updates.items():
        prev_val = str(prev_cfg.get(key, ""))

        # Upsert into system_config table
        stmt = (
            pg_insert(SystemConfigEntity)
            .values(key=key, value=new_val, updated_at=now, updated_by=payload.updated_by)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": new_val, "updated_at": now, "updated_by": payload.updated_by},
            )
        )
        await session.execute(stmt)

        # Append SystemConfigEvent to the event store for audit trail / replay
        event = StoredEvent(
            event_id=str(uuid4()),
            aggregate_type="SystemConfig",
            aggregate_id="system",           # singleton aggregate
            event_type="SystemConfigEvent",
            event_version=1,
            sequence_number=0,               # event store repo handles real seq
            actor_id=payload.updated_by,
            payload={
                "config_key": key,
                "previous_value": prev_val,
                "new_value": new_val,
                "changed_by": payload.updated_by,
            },
            occurred_at_utc=now,
        )
        # Use raw insert to bypass the sequence-number UoW logic (singleton aggregate)
        from sqlalchemy import text
        seq_result = await session.execute(
            text("SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM events WHERE aggregate_id = 'system'")
        )
        event.sequence_number = seq_result.scalar_one()
        session.add(event)

    await session.commit()

    cfg = await get_runtime_config(session)
    return SystemConfigResponse(
        replenishment_target_days=int(cfg["replenishment_target_days"]),
        replenishment_lead_time_days=int(cfg["replenishment_lead_time_days"]),
        replenishment_weekly_budget=int(cfg["replenishment_weekly_budget"]),
        costing_strategy=str(cfg["costing_strategy"]),
        ai_confidence_threshold=float(cfg["ai_confidence_threshold"]),
        margin_target=float(cfg["margin_target"]),
        overrides=cfg.get("_overrides", {}),
    )


# ── Apply margin to existing products ─────────────────────────────────────────


class ApplyMarginRequest(BaseModel):
    applied_by: str = "system"
    margin_override: float | None = None   # if set, use this instead of the DB config value


class ApplyMarginProductResult(BaseModel):
    product_id: str
    product_name: str
    old_price: float
    new_price: float
    avg_cost: float


class ApplyMarginResponse(BaseModel):
    margin_target: float
    updated: int
    skipped: int   # no cost data available
    products: list[ApplyMarginProductResult]


@router.post("/apply-margin", response_model=ApplyMarginResponse)
async def apply_margin_to_all_products(
    payload: ApplyMarginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ApplyMarginResponse:
    """
    Re-price every product in the catalog using the current margin target.
    new_price = cost / (1 − margin_target)

    Cost basis (in priority order):
      1. Quantity-weighted average from InventoryLayerCreatedEvent records
      2. base_price — the price the product was originally created with
         (products added manually through the catalog use their entry price
          as the cost, since no intake event exists yet)

    Each price change fires a PriceOverriddenEvent for the audit trail.
    """
    from decimal import Decimal
    from uuid import UUID
    from sqlalchemy import text

    from app.application.handlers.product_handlers import ProductCommandHandler
    from app.domain.commands.product_commands import ApplyPriceOverrideCommand

    cfg = await get_runtime_config(session)
    margin_target: float = (
        float(payload.margin_override)
        if payload.margin_override is not None
        else float(cfg.get("margin_target", 0.70))
    )
    margin_divisor = Decimal(str(1.0 - max(0.0, min(margin_target, 0.9999))))

    # Weighted-average cost per product from intake events
    cost_result = await session.execute(text("""
        SELECT
            payload->>'product_id'                                          AS product_id,
            SUM((payload->>'quantity_received')::int
                * (payload->>'unit_cost')::numeric)
            / NULLIF(SUM((payload->>'quantity_received')::int), 0)          AS avg_cost
        FROM events
        WHERE event_type = 'InventoryLayerCreatedEvent'
        GROUP BY payload->>'product_id'
    """))
    avg_cost_by_product: dict[str, Decimal] = {
        row.product_id: Decimal(str(row.avg_cost))
        for row in cost_result.all()
        if row.avg_cost is not None
    }

    # All products
    products_result = await session.execute(select(ProductReadEntity))
    products = products_result.scalars().all()

    handler = ProductCommandHandler(session)
    # Use a deterministic system UUID for the authorized_by field
    system_uuid = UUID("00000000-0000-0000-0000-000000000001")

    updated_list: list[ApplyMarginProductResult] = []
    skipped = 0

    for product in products:
        pid = str(product.id)
        # Priority 1: weighted avg from intake events
        avg_cost = avg_cost_by_product.get(pid)
        # Priority 2: fall back to base_price (the price entered at product creation,
        # which for manually-created products equals the purchase/cost price)
        if avg_cost is None or avg_cost <= Decimal("0"):
            base = Decimal(str(product.base_price))
            if base <= Decimal("0"):
                skipped += 1
                continue
            avg_cost = base

        new_price = (avg_cost / margin_divisor).quantize(Decimal("0.01"))
        old_price = float(product.current_price)

        await handler.handle_apply_price_override(
            ApplyPriceOverrideCommand(
                product_id=UUID(pid),
                new_price=new_price,
                authorized_by=system_uuid,
            )
        )
        updated_list.append(ApplyMarginProductResult(
            product_id=pid,
            product_name=product.name,
            old_price=old_price,
            new_price=float(new_price),
            avg_cost=float(avg_cost),
        ))
        logger.info(
            "Margin reprice: '%s' %.2f → %.2f (cost=%.4f, margin=%.0f%%)",
            product.name, old_price, new_price, avg_cost, margin_target * 100,
        )

    return ApplyMarginResponse(
        margin_target=margin_target,
        updated=len(updated_list),
        skipped=skipped,
        products=updated_list,
    )
