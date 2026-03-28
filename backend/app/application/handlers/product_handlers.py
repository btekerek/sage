from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.product import Product
from app.domain.commands.product_commands import (
    ApplyPriceOverrideCommand,
    CreateProductCommand,
)
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.unit_of_work import UnitOfWork


class ProductCommandHandler:
    """
    Handles commands for Product aggregate.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ProductRepository(session)

    async def handle_create_product(
        self, command: CreateProductCommand
    ) -> None:
        """
        Create a new product and persist its creation event.
        """
        product = Product(
            name=command.name,
            unit_price=command.unit_price,
            category_id=command.category_id,
            aggregate_id=command.aggregate_id,
        )

        async with UnitOfWork(self._session) as uow:
            uow.track(product)

    async def handle_apply_price_override(
        self, command: ApplyPriceOverrideCommand
    ) -> None:
        """
        Load an existing product and apply a price override.
        """
        product = await self._repository.get(command.product_id)
        if product is None:
            raise ValueError(f"Product {command.product_id} not found.")

        product.apply_price_override(
            new_price=command.new_price,
            authorized_by=command.authorized_by,
        )

        async with UnitOfWork(self._session) as uow:
            uow.track(product)
