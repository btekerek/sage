import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.events.base import BaseEvent


class AggregateRoot:
    """
    The parent class for every aggregate in the system.
    Tracks pending events and provides identity and versioning.
    """

    def __init__(self, aggregate_id: uuid.UUID | None = None):
        self.aggregate_id: uuid.UUID = aggregate_id or uuid.uuid4()
        self.version: int = 0
        self._pending_events: list["BaseEvent"] = []

    def _raise_event(self, event: "BaseEvent") -> None:
        """
        Record a new event and apply it to update internal state.
        Events are not persisted here — that is the repository's job.
        """
        self._pending_events.append(event)
        self._apply(event)
        self.version += 1

    def _apply(self, event: "BaseEvent") -> None:
        """
        Apply an event to update the aggregate's state.
        Each aggregate overrides this to handle its own event types.
        """
        method_name = f"_on_{event.event_type}"
        handler = getattr(self, method_name, None)
        if handler:
            handler(event)

    def collect_events(self) -> list["BaseEvent"]:
        """
        Return all pending events and clear the internal list.
        Called by the Unit of Work before persisting.
        """
        events = self._pending_events.copy()
        self._pending_events.clear()
        return events

    def load_from_history(self, events: list["BaseEvent"]) -> None:
        """
        Reconstruct aggregate state by replaying a list of past events.
        Called by the Repository when loading an aggregate.
        """
        for event in events:
            self._apply(event)
            self.version += 1