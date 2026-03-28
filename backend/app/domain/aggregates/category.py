import uuid

from app.domain.aggregates.base import AggregateRoot


class Category(AggregateRoot):
    """
    Represents a product category. Supports hierarchical structure
    through an optional parent_category_id.
    """

    def __init__(
        self,
        name: str,
        aggregate_id: uuid.UUID | None = None,
        parent_category_id: uuid.UUID | None = None,
    ):
        super().__init__(aggregate_id)
        self.name = name
        self.parent_category_id = parent_category_id

    def rename(self, new_name: str) -> None:
        if not new_name.strip():
            raise ValueError("Category name cannot be empty.")
        self.name = new_name