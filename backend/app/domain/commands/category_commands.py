import uuid
from dataclasses import dataclass


@dataclass
class CreateCategoryCommand:
    """
    Command to create a new product category.
    """
    name: str
    parent_category_id: uuid.UUID = None
    aggregate_id: uuid.UUID = None

    def __post_init__(self):
        if self.aggregate_id is None:
            self.aggregate_id = uuid.uuid4()
