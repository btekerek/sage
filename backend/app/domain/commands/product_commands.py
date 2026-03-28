import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class CreateProductCommand:
    """
    Command to create a new product in the catalog.
    """
    name: str
    unit_price: Decimal
    category_id: uuid.UUID
    aggregate_id: uuid.UUID = None

    def __post_init__(self):
        if self.aggregate_id is None:
            self.aggregate_id = uuid.uuid4()


@dataclass
class ApplyPriceOverrideCommand:
    """
    Command to change the retail price of an existing product.
    """
    product_id: uuid.UUID
    new_price: Decimal
    authorized_by: uuid.UUID
