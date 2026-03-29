"""Base projector class for read-side event stream materialization."""

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from app.domain.events.base import BaseEvent
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseProjector(ABC, Generic[T]):
    """Abstract base class for projectors that materialize read models from event streams."""

    @abstractmethod
    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        """
        Project a single event into the read model.

        Args:
            event: The domain event to project
            session: Async database session
        """
        pass

    @abstractmethod
    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> T | None:
        """
        Retrieve the current materialized state for an aggregate.

        Args:
            aggregate_id: The aggregate ID to retrieve state for
            session: Async database session

        Returns:
            The current read model state, or None if not found
        """
        pass
