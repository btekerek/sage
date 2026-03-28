from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.draft_sale import DraftSale
from app.domain.commands.sale_commands import (
    AddLineItemCommand,
    CreateDraftSaleCommand,
    FinalizeSaleCommand,
    RemoveLineItemCommand,
    UpdateLineItemCommand,
    VoidSaleCommand,
)
from app.infrastructure.repositories.unit_of_work import UnitOfWork


class SaleCommandHandler:
    """
    Handles commands for DraftSale aggregate.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle_create_draft_sale(
        self, command: CreateDraftSaleCommand
    ) -> None:
        """
        Create a new in-progress transaction.
        """
        sale = DraftSale(
            operator_id=command.operator_id,
            session_id=command.session_id,
            aggregate_id=command.aggregate_id,
        )

        async with UnitOfWork(self._session) as uow:
            uow.track(sale)

    async def handle_add_line_item(
        self, command: AddLineItemCommand
    ) -> None:
        """
        Add a product to an open draft sale.
        """
        # Note: In a full implementation, we'd load the sale from the repository.
        # For now, we create a new instance with minimal state.
        # This would be enhanced in Slice 5 when we add read models.
        sale = DraftSale(
            operator_id=None,  # Would be loaded from history
            session_id=None,
            aggregate_id=command.sale_id,
        )

        sale.add_item(
            product_id=command.product_id,
            product_name=command.product_name,
            unit_price=command.unit_price,
            quantity=command.quantity,
            available_stock=command.available_stock,
        )

        async with UnitOfWork(self._session) as uow:
            uow.track(sale)

    async def handle_remove_line_item(
        self, command: RemoveLineItemCommand
    ) -> None:
        """
        Remove a product from an open draft sale.
        """
        sale = DraftSale(
            operator_id=None,
            session_id=None,
            aggregate_id=command.sale_id,
        )

        sale.remove_item(command.product_id)

        async with UnitOfWork(self._session) as uow:
            uow.track(sale)

    async def handle_update_line_item(
        self, command: UpdateLineItemCommand
    ) -> None:
        """
        Change the quantity of a line item in an open draft sale.
        """
        sale = DraftSale(
            operator_id=None,
            session_id=None,
            aggregate_id=command.sale_id,
        )

        sale.update_quantity(
            product_id=command.product_id,
            quantity=command.quantity,
            available_stock=command.available_stock,
        )

        async with UnitOfWork(self._session) as uow:
            uow.track(sale)

    async def handle_finalize_sale(
        self, command: FinalizeSaleCommand
    ) -> None:
        """
        Complete and finalize a draft sale.
        """
        sale = DraftSale(
            operator_id=None,
            session_id=None,
            aggregate_id=command.sale_id,
        )

        sale.finalize(command.payment_method)

        async with UnitOfWork(self._session) as uow:
            uow.track(sale)

    async def handle_void_sale(
        self, command: VoidSaleCommand
    ) -> None:
        """
        Cancel an in-progress draft sale.
        """
        sale = DraftSale(
            operator_id=None,
            session_id=None,
            aggregate_id=command.sale_id,
        )

        sale.void(command.reason)

        async with UnitOfWork(self._session) as uow:
            uow.track(sale)
