from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.inventory_layer import InventoryLayer
from app.domain.commands.inventory_commands import CreateInventoryLayerCommand
from app.infrastructure.repositories.unit_of_work import UnitOfWork


class InventoryCommandHandler:
    """
    Handles commands for InventoryLayer aggregate.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle_create_inventory_layer(
        self, command: CreateInventoryLayerCommand
    ) -> None:
        """
        Create a new inventory cost layer from a supplier delivery.
        """
        layer = InventoryLayer(
            product_id=command.product_id,
            quantity_received=command.quantity_received,
            unit_cost=command.unit_cost,
            supplier_ref=command.supplier_ref,
            aggregate_id=command.aggregate_id,
            intake_at=command.intake_at,
        )

        async with UnitOfWork(self._session) as uow:
            uow.track(layer)
