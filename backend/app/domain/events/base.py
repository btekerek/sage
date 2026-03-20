import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

@dataclass
class BaseEvent:
    aggregate_id: uuid.UUID
    aggregate_type: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    sequence_number: int = field(default=0)
    causation_id: uuid.UUID | None = field(default=None)

    @property
    def event_type(self) -> str:
        return self.__class__.__name__

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "occurred_at": self.occurred_at.isoformat(),
            "sequence_number": self.sequence_number,
            "causation_id": str(self.causation_id) if self.causation_id else None,
        }