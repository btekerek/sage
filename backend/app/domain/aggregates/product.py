import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.aggregates.base import AggregateRoot
from app.domain.events.events import PriceOverrideEvent


@dataclass
class Product(AggregateRoot):
    """
    Represents a product in the catalogue.
    Owns its own price history through PriceOverrideEvents.
    """

    def __init__(
        self,
        name: str,
        unit_price: Decimal,
        category_id: uuid.UUID,
        aggregate_id: uuid.UUID | None = None,
        is_active: bool = True,
    ):
        super().__init__(aggregate_id)
        self.name = name
        self.unit_price = unit_price
        self.category_id = category_id
        self.is_active = is_active

    def apply_price_override(
        self,
        new_price: Decimal,
        authorized_by: uuid.UUID,
    ) -> PriceOverrideEvent:
        """
        Change the retail price of this product.
        Raises a PriceOverrideEvent which updates internal state via _apply.
        """
        if new_price <= Decimal("0.00"):
            raise ValueError("Price must be greater than zero.")

        event = PriceOverrideEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="Product",
            product_id=self.aggregate_id,
            previous_price=self.unit_price,
            new_price=new_price,
            authorized_by=authorized_by,
        )
        self._raise_event(event)
        return event

    def deactivate(self) -> None:
        if not self.is_active:
            raise ValueError("Product is already inactive.")
        self.is_active = False

    def activate(self) -> None:
        if self.is_active:
            raise ValueError("Product is already active.")
        self.is_active = True

    # ── Event handlers ─────────────────────────────────────────

    def _on_PriceOverrideEvent(self, event: PriceOverrideEvent) -> None:
        self.unit_price = event.new_price