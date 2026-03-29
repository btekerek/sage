import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.aggregates.base import AggregateRoot
from app.domain.events.events import InventoryLayerCreatedEvent


class InventoryLayer(AggregateRoot):
    """
    Represents a single inventory cost layer created from a supplier delivery.
    Tracks the quantity received, quantity remaining, and unit cost.
    FIFO depletion is applied by consuming the oldest layers first.
    """

    def __init__(
        self,
        product_id: uuid.UUID,
        quantity_received: int,
        unit_cost: Decimal,
        supplier_ref: str,
        aggregate_id: uuid.UUID | None = None,
        intake_at: datetime | None = None,
    ):
        super().__init__(aggregate_id)
        event = InventoryLayerCreatedEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="InventoryLayer",
            product_id=product_id,
            quantity_received=quantity_received,
            unit_cost=unit_cost,
            supplier_ref=supplier_ref,
        )
        self._raise_event(event)
        # intake_at is not in the event; set it directly after raising
        self.intake_at = intake_at or datetime.now(timezone.utc)

    def consume(self, qty: int) -> Decimal:
        """
        Deplete this layer by qty units.
        Returns the COGS contribution from this layer.
        Raises if qty exceeds quantity_remaining.
        """
        if qty <= 0:
            raise ValueError("Quantity to consume must be positive.")
        if qty > self.quantity_remaining:
            raise ValueError(
                f"Cannot consume {qty} units — only {self.quantity_remaining} remaining."
            )
        self.quantity_remaining -= qty
        return Decimal(qty) * self.unit_cost

    @property
    def is_exhausted(self) -> bool:
        return self.quantity_remaining == 0

    def _on_InventoryLayerCreatedEvent(self, event: InventoryLayerCreatedEvent) -> None:
        self.product_id = event.product_id
        self.quantity_received = event.quantity_received
        self.quantity_remaining = event.quantity_received
        self.unit_cost = event.unit_cost
        self.supplier_ref = event.supplier_ref
