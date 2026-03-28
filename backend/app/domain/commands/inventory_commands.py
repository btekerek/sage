import uuid
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone


@dataclass
class CreateInventoryLayerCommand:
    """
    Command to create a new inventory cost layer from a supplier delivery.
    """
    product_id: uuid.UUID
    quantity_received: int
    unit_cost: Decimal
    supplier_ref: str
    intake_at: datetime | None = None
    aggregate_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.aggregate_id is None:
            self.aggregate_id = uuid.uuid4()
        if self.intake_at is None:
            self.intake_at = datetime.now(timezone.utc)
