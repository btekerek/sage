import uuid
from decimal import Decimal
from datetime import datetime, timezone

from app.domain.aggregates.base import AggregateRoot


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
        self.product_id = product_id
        self.quantity_received = quantity_received
        self.quantity_remaining = quantity_received
        self.unit_cost = unit_cost
        self.supplier_ref = supplier_ref
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