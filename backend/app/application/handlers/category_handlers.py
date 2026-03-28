from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.category import Category
from app.domain.commands.category_commands import CreateCategoryCommand
from app.infrastructure.repositories.unit_of_work import UnitOfWork


class CategoryCommandHandler:
    """
    Handles commands for Category aggregate.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle_create_category(
        self, command: CreateCategoryCommand
    ) -> None:
        """
        Create a new product category.
        """
        category = Category(
            name=command.name,
            aggregate_id=command.aggregate_id,
            parent_category_id=command.parent_category_id,
        )

        async with UnitOfWork(self._session) as uow:
            uow.track(category)
