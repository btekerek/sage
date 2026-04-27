"""
Deterministic Replay API.

GET /api/replay/bounds
    Returns the temporal range of the event store so the frontend
    can initialise its date picker sensibly.

GET /api/replay/snapshot?as_of=<ISO-8601>
    Returns a full system snapshot reconstructed from the event log
    up to the requested timestamp — no live read-model tables involved.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.services.replay_service import (
    ReplayBounds,
    ReplaySnapshot,
    get_event_bounds,
    replay_at,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/replay", tags=["replay"])


@router.get("/bounds", response_model=ReplayBounds)
async def event_bounds(
    session: AsyncSession = Depends(get_db_session),
) -> ReplayBounds:
    """Return the first and last event timestamps in the event store."""
    return await get_event_bounds(session)


@router.get("/snapshot", response_model=ReplaySnapshot)
async def snapshot(
    as_of: str = Query(..., description="ISO-8601 datetime, e.g. 2026-04-20T10:00:00Z"),
    session: AsyncSession = Depends(get_db_session),
) -> ReplaySnapshot:
    """
    Replay all events up to `as_of` and return the full system state
    at that exact point in time.
    """
    try:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid datetime format: '{as_of}'. Use ISO-8601, e.g. 2026-04-20T10:00:00Z",
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    try:
        return await replay_at(session, dt)
    except Exception as exc:
        logger.error("Replay failed for as_of=%s: %s", as_of, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Replay failed: {exc}",
        ) from exc
