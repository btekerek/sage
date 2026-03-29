import uuid

from app.domain.aggregates.base import AggregateRoot
from app.domain.events.events import CategoryCreatedEvent


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
        event = CategoryCreatedEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type="Category",
            name=name,
            parent_category_id=parent_category_id,
        )
        self._raise_event(event)

    def rename(self, new_name: str) -> None:
        if not new_name.strip():
            raise ValueError("Category name cannot be empty.")
        self.name = new_name

    def _on_CategoryCreatedEvent(self, event: CategoryCreatedEvent) -> None:
        self.name = event.name
        self.parent_category_id = event.parent_category_id
