import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.events.base import BaseEvent

# ── Product Events ─────────────────────────────────────────────


@dataclass
class ProductCreatedEvent(BaseEvent):
    """Raised when a new product is added to the catalogue."""

    name: str = field(default="")
    unit_price: Decimal = field(default=Decimal("0.00"))
    category_id: uuid.UUID = field(default_factory=uuid.uuid4)
    is_active: bool = field(default=True)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "name": self.name,
            "unit_price": str(self.unit_price),
            "category_id": str(self.category_id),
            "is_active": self.is_active,
        }
        return base


# ── Category Events ─────────────────────────────────────────────


@dataclass
class CategoryCreatedEvent(BaseEvent):
    """Raised when a new category is created."""

    name: str = field(default="")
    parent_category_id: uuid.UUID | None = field(default=None)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "name": self.name,
            "parent_category_id": (
                str(self.parent_category_id) if self.parent_category_id else None
            ),
        }
        return base


# ── InventoryLayer Events ───────────────────────────────────────


@dataclass
class InventoryLayerCreatedEvent(BaseEvent):
    """Raised when a supplier delivery creates a new cost layer."""

    product_id: uuid.UUID = field(default_factory=uuid.uuid4)
    quantity_received: int = field(default=0)
    unit_cost: Decimal = field(default=Decimal("0.00"))
    supplier_ref: str = field(default="")

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "product_id": str(self.product_id),
            "quantity_received": self.quantity_received,
            "unit_cost": str(self.unit_cost),
            "supplier_ref": self.supplier_ref,
        }
        return base


# ── DraftSale Events ────────────────────────────────────────────


@dataclass
class DraftSaleCreatedEvent(BaseEvent):
    """Raised when a new POS transaction session is opened."""

    operator_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "operator_id": str(self.operator_id),
            "session_id": str(self.session_id),
        }
        return base


@dataclass
class LineItemAddedEvent(BaseEvent):
    """Raised when a product is added to the cart."""

    product_id: uuid.UUID = field(default_factory=uuid.uuid4)
    product_name: str = field(default="")
    unit_price: Decimal = field(default=Decimal("0.00"))
    quantity: int = field(default=0)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "product_id": str(self.product_id),
            "product_name": self.product_name,
            "unit_price": str(self.unit_price),
            "quantity": self.quantity,
        }
        return base


@dataclass
class LineItemRemovedEvent(BaseEvent):
    """Raised when a product is removed from the cart."""

    product_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "product_id": str(self.product_id),
        }
        return base


@dataclass
class LineItemUpdatedEvent(BaseEvent):
    """Raised when a cart item's quantity is changed."""

    product_id: uuid.UUID = field(default_factory=uuid.uuid4)
    quantity: int = field(default=0)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "product_id": str(self.product_id),
            "quantity": self.quantity,
        }
        return base


# ── Sale Events ────────────────────────────────────────────────


@dataclass
class SaleLineItem:
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


@dataclass
class SaleEvent(BaseEvent):
    """
    Raised when a transaction is finalized at the POS.
    Triggers FIFO inventory depletion and financial summary update.
    """

    operator_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    payment_method: str = field(default="")
    line_items: list[SaleLineItem] = field(default_factory=list)
    total_amount: Decimal = field(default=Decimal("0.00"))

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "operator_id": str(self.operator_id),
            "session_id": str(self.session_id),
            "payment_method": self.payment_method,
            "total_amount": str(self.total_amount),
            "line_items": [
                {
                    "product_id": str(item.product_id),
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "line_total": str(item.line_total),
                }
                for item in self.line_items
            ],
        }
        return base


@dataclass
class VoidEvent(BaseEvent):
    """
    Raised when an in-progress transaction is cancelled before payment.
    No inventory or financial update is triggered.
    """

    operator_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    reason: str = field(default="")

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "operator_id": str(self.operator_id),
            "session_id": str(self.session_id),
            "reason": self.reason,
        }
        return base


# ── Inventory Events ───────────────────────────────────────────


@dataclass
class IntakeLineItem:
    product_id: uuid.UUID
    product_name: str
    quantity: int
    unit_cost: Decimal
    supplier_ref: str


@dataclass
class InventoryIntakeEvent(BaseEvent):
    """
    Raised when a supplier invoice is approved by a manager.
    Creates one cost layer per line item in the inventory projector.
    """

    supplier_ref: str = field(default="")
    invoice_ref: str = field(default="")
    approved_by: uuid.UUID = field(default_factory=uuid.uuid4)
    line_items: list[IntakeLineItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "supplier_ref": self.supplier_ref,
            "invoice_ref": self.invoice_ref,
            "approved_by": str(self.approved_by),
            "line_items": [
                {
                    "product_id": str(item.product_id),
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_cost": str(item.unit_cost),
                    "supplier_ref": item.supplier_ref,
                }
                for item in self.line_items
            ],
        }
        return base


# ── Price Events ───────────────────────────────────────────────


@dataclass
class PriceOverrideEvent(BaseEvent):
    """
    Raised when a manager manually changes the retail price of a product.
    """

    product_id: uuid.UUID = field(default_factory=uuid.uuid4)
    previous_price: Decimal = field(default=Decimal("0.00"))
    new_price: Decimal = field(default=Decimal("0.00"))
    authorized_by: uuid.UUID = field(default_factory=uuid.uuid4)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "product_id": str(self.product_id),
            "previous_price": str(self.previous_price),
            "new_price": str(self.new_price),
            "authorized_by": str(self.authorized_by),
        }
        return base


# ── System Events ──────────────────────────────────────────────


@dataclass
class SystemConfigEvent(BaseEvent):
    """
    Raised when a system administrator changes a configuration parameter.
    Enables precise reconstruction of config state at any historical point.
    """

    config_key: str = field(default="")
    previous_value: str = field(default="")
    new_value: str = field(default="")
    changed_by: uuid.UUID = field(default_factory=uuid.uuid4)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["payload"] = {
            "config_key": self.config_key,
            "previous_value": self.previous_value,
            "new_value": self.new_value,
            "changed_by": str(self.changed_by),
        }
        return base
