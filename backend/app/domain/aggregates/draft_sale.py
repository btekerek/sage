import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from app.domain.aggregates.base import AggregateRoot
from app.domain.events.events import (
    DraftSaleCreatedEvent,
    LineItemAddedEvent,
    LineItemRemovedEvent,
    LineItemUpdatedEvent,
    SaleEvent,
    SaleLineItem,
    VoidEvent,
)


class SaleStatus(Enum):
    EMPTY = "EMPTY"
    ACTIVE = "ACTIVE"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


@dataclass
class CartItem:
    product_id: uuid.UUID
    product_name: str
    unit_price: Decimal
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class DraftSale(AggregateRoot):
    """
    Represents an in-progress transaction at the POS.
    Lifecycle: EMPTY → ACTIVE → FINALIZED or VOIDED.
    FINALIZED and VOIDED are terminal — no further transitions possible.
    """

    def __init__(
        self,
        operator_id: uuid.UUID,
        session_id: uuid.UUID,
        aggregate_id: uuid.UUID | None = None,
    ):
        super().__init__(aggregate_id)
        event = DraftSaleCreatedEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="DraftSale",
            operator_id=operator_id or uuid.uuid4(),
            session_id=session_id or uuid.uuid4(),
        )
        self._raise_event(event)

    # ── Cart operations ────────────────────────────────────────

    def add_item(
        self,
        product_id: uuid.UUID,
        product_name: str,
        unit_price: Decimal,
        quantity: int,
        available_stock: int,
    ) -> None:
        self._guard_not_terminal()
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")

        current_qty = self.items[product_id].quantity if product_id in self.items else 0
        if current_qty + quantity > available_stock:
            raise ValueError(
                f"Insufficient stock — requested {current_qty + quantity}, "
                f"available {available_stock}."
            )

        event = LineItemAddedEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="DraftSale",
            product_id=product_id,
            product_name=product_name,
            unit_price=unit_price,
            quantity=quantity,
        )
        self._raise_event(event)

    def remove_item(self, product_id: uuid.UUID) -> None:
        self._guard_not_terminal()
        if product_id not in self.items:
            raise ValueError("Item not in cart.")
        event = LineItemRemovedEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="DraftSale",
            product_id=product_id,
        )
        self._raise_event(event)

    def update_quantity(
        self,
        product_id: uuid.UUID,
        quantity: int,
        available_stock: int,
    ) -> None:
        self._guard_not_terminal()
        if product_id not in self.items:
            raise ValueError("Item not in cart.")
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
        if quantity > available_stock:
            raise ValueError(
                f"Insufficient stock — requested {quantity}, available {available_stock}."
            )
        event = LineItemUpdatedEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="DraftSale",
            product_id=product_id,
            quantity=quantity,
        )
        self._raise_event(event)

    # ── Transaction operations ─────────────────────────────────

    def finalize(self, payment_method: str) -> SaleEvent:
        self._guard_not_terminal()
        if self.status == SaleStatus.EMPTY:
            raise ValueError("Cannot finalize an empty cart.")

        line_items = [
            SaleLineItem(
                product_id=item.product_id,
                product_name=item.product_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in self.items.values()
        ]

        event = SaleEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="DraftSale",
            operator_id=self.operator_id,
            session_id=self.session_id,
            payment_method=payment_method,
            line_items=line_items,
            total_amount=self.total,
        )
        self._raise_event(event)
        return event

    def void(self, reason: str = "") -> VoidEvent:
        self._guard_not_terminal()
        event = VoidEvent(  # type: ignore[call-arg]
            aggregate_id=self.aggregate_id,
            aggregate_type="DraftSale",
            operator_id=self.operator_id,
            session_id=self.session_id,
            reason=reason,
        )
        self._raise_event(event)
        return event

    # ── Computed properties ────────────────────────────────────

    @property
    def total(self) -> Decimal:
        total = Decimal("0.00")
        for item in self.items.values():
            total += item.line_total
        return total

    # ── Event handlers ─────────────────────────────────────────

    def _on_SaleEvent(self, event: SaleEvent) -> None:
        self.status = SaleStatus.FINALIZED

    def _on_VoidEvent(self, event: VoidEvent) -> None:
        self.status = SaleStatus.VOIDED

    def _on_DraftSaleCreatedEvent(self, event: DraftSaleCreatedEvent) -> None:
        self.operator_id = event.operator_id
        self.session_id = event.session_id
        self.status = SaleStatus.EMPTY
        self.items: dict[uuid.UUID, CartItem] = {}

    def _on_LineItemAddedEvent(self, event: LineItemAddedEvent) -> None:
        if event.product_id in self.items:
            self.items[event.product_id].quantity += event.quantity
        else:
            self.items[event.product_id] = CartItem(
                product_id=event.product_id,
                product_name=event.product_name,
                unit_price=event.unit_price,
                quantity=event.quantity,
            )
        self.status = SaleStatus.ACTIVE

    def _on_LineItemRemovedEvent(self, event: LineItemRemovedEvent) -> None:
        del self.items[event.product_id]
        if not self.items:
            self.status = SaleStatus.EMPTY

    def _on_LineItemUpdatedEvent(self, event: LineItemUpdatedEvent) -> None:
        self.items[event.product_id].quantity = event.quantity

    # ── Guards ─────────────────────────────────────────────────

    def _guard_not_terminal(self) -> None:
        if self.status == SaleStatus.FINALIZED:
            raise ValueError("Transaction is already finalized.")
        if self.status == SaleStatus.VOIDED:
            raise ValueError("Transaction is already voided.")
