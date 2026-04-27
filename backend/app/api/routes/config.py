"""
System Configuration API  (UC-12).

GET  /api/config          — return current effective values (DB overrides + env defaults)
PATCH /api/config         — update one or more runtime config values
                            each change is also appended to the event store

Configurable keys:
  replenishment_budget          float  > 0
  replenishment_target_days     int    > 0
  costing_strategy              FIFO | WAC
  ai_confidence_threshold       float  0.0 – 1.0
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
from app.infrastructure.projectors.read_entities import SystemConfigEntity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

# Keys that can be changed at runtime
_ALLOWED_KEYS = {
    "replenishment_budget",
    "replenishment_target_days",
    "costing_strategy",
    "ai_confidence_threshold",
}


# ── Pydantic models ────────────────────────────────────────────────────────────

class SystemConfigResponse(BaseModel):
    replenishment_budget: float
    replenishment_target_days: int
    costing_strategy: str
    ai_confidence_threshold: float
    # metadata
    overrides: dict[str, str]   # which keys are overridden in DB (vs env default)


class PatchConfigRequest(BaseModel):
    replenishment_budget: float | None = Field(None, gt=0)
    replenishment_target_days: int | None = Field(None, gt=0)
    costing_strategy: str | None = None
    ai_confidence_threshold: float | None = Field(None, ge=0.0, le=1.0)
    updated_by: str = "system"


# ── Helper ─────────────────────────────────────────────────────────────────────

async def get_runtime_config(session: AsyncSession) -> dict:
    """
    Return the effective runtime config dict, merging DB overrides over env defaults.
    Import and call this in any route that needs live config values.
    """
    env = get_settings()
    defaults = {
        "replenishment_budget": env.replenishment_budget,
        "replenishment_target_days": env.replenishment_target_days,
        "costing_strategy": env.costing_strategy,
        "ai_confidence_threshold": env.ai_confidence_threshold,
    }

    result = await session.execute(select(SystemConfigEntity))
    rows = result.scalars().all()
    overrides = {r.key: r.value for r in rows}

    merged = dict(defaults)
    for key, raw_val in overrides.items():
        if key not in defaults:
            continue
        try:
            if key in ("replenishment_budget", "ai_confidence_threshold"):
                merged[key] = float(raw_val)
            elif key == "replenishment_target_days":
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
        replenishment_budget=float(cfg["replenishment_budget"]),
        replenishment_target_days=int(cfg["replenishment_target_days"]),
        costing_strategy=str(cfg["costing_strategy"]),
        ai_confidence_threshold=float(cfg["ai_confidence_threshold"]),
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

    if payload.replenishment_budget is not None:
        updates["replenishment_budget"] = str(payload.replenishment_budget)
    if payload.replenishment_target_days is not None:
        updates["replenishment_target_days"] = str(payload.replenishment_target_days)
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
        replenishment_budget=float(cfg["replenishment_budget"]),
        replenishment_target_days=int(cfg["replenishment_target_days"]),
        costing_strategy=str(cfg["costing_strategy"]),
        ai_confidence_threshold=float(cfg["ai_confidence_threshold"]),
        overrides=cfg.get("_overrides", {}),
    )
