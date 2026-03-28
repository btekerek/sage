import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class CreateDraftSaleCommand:
    """
    Command to start a new in-progress transaction.
    """
    operator_id: uuid.UUID
    session_id: uuid.UUID
    aggregate_id: uuid.UUID = None

    def __post_init__(self):
        if self.aggregate_id is None:
            self.aggregate_id = uuid.uuid4()


@dataclass
class AddLineItemCommand:
    """
    Command to add a product to an open draft sale.
    """
    sale_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    unit_price: Decimal
    quantity: int
    available_stock: int


@dataclass
class RemoveLineItemCommand:
    """
    Command to remove a product from an open draft sale.
    """
    sale_id: uuid.UUID
    product_id: uuid.UUID


@dataclass
class UpdateLineItemCommand:
    """
    Command to change the quantity of a line item in an open draft sale.
    """
    sale_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    available_stock: int


@dataclass
class FinalizeSaleCommand:
    """
    Command to complete a draft sale and finalize the transaction.
    Triggers inventory depletion and accounting updates.
    """
    sale_id: uuid.UUID
    payment_method: str


@dataclass
class VoidSaleCommand:
    """
    Command to cancel an in-progress draft sale.
    No inventory or financial impact.
    """
    sale_id: uuid.UUID
    reason: str = ""
