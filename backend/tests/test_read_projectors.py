# mypy: disable-error-code=import-not-found
# pyright: reportMissingImports=false
"""Integration tests for read-side projectors and query endpoints."""

import json
from decimal import Decimal
from uuid import uuid4

import pytest  # type: ignore[import-not-found]
from app.application.handlers.category_handlers import CategoryCommandHandler
from app.application.handlers.inventory_handlers import InventoryCommandHandler
from app.application.handlers.product_handlers import ProductCommandHandler
from app.application.handlers.sale_handlers import SaleCommandHandler
from app.core.settings import get_settings
from app.domain.commands.category_commands import CreateCategoryCommand
from app.domain.commands.inventory_commands import CreateInventoryLayerCommand
from app.domain.commands.product_commands import (
    ApplyPriceOverrideCommand,
    CreateProductCommand,
)
from app.domain.commands.sale_commands import (
    AddLineItemCommand,
    CreateDraftSaleCommand,
    FinalizeSaleCommand,
    RemoveLineItemCommand,
    VoidSaleCommand,
)
from app.infrastructure.projectors.read_entities import (
    CategoryReadEntity,
    DraftSaleReadEntity,
    InventoryLayerReadEntity,
    ProductReadEntity,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def make_session_factory():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_product_projector_create() -> None:
    """Test product creation is projected to the read model."""
    session_factory = make_session_factory()
    category_id = uuid4()
    product_id = uuid4()

    async with session_factory() as session:
        handler = ProductCommandHandler(session)
        command = CreateProductCommand(
            name="Test Product",
            unit_price=Decimal("99.99"),
            category_id=category_id,
            aggregate_id=product_id,
        )
        await handler.handle_create_product(command)

    async with session_factory() as session:
        stmt = select(ProductReadEntity).where(ProductReadEntity.id == product_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert entity.name == "Test Product"
    assert float(entity.current_price) == 99.99


@pytest.mark.asyncio
async def test_product_projector_price_override() -> None:
    """Test price override is projected to the read model."""
    session_factory = make_session_factory()
    category_id = uuid4()
    product_id = uuid4()

    async with session_factory() as session:
        handler = ProductCommandHandler(session)
        create_cmd = CreateProductCommand(
            name="Override Product",
            unit_price=Decimal("50.00"),
            category_id=category_id,
            aggregate_id=product_id,
        )
        await handler.handle_create_product(create_cmd)

    async with session_factory() as session:
        handler = ProductCommandHandler(session)
        override_cmd = ApplyPriceOverrideCommand(
            product_id=product_id,
            new_price=Decimal("75.00"),
            authorized_by=uuid4(),
        )
        await handler.handle_apply_price_override(override_cmd)

    async with session_factory() as session:
        stmt = select(ProductReadEntity).where(ProductReadEntity.id == product_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert float(entity.current_price) == 75.00
    assert entity.last_price_override_at is not None


@pytest.mark.asyncio
async def test_category_projector_create() -> None:
    """Test category creation is projected to the read model."""
    session_factory = make_session_factory()
    category_id = uuid4()

    async with session_factory() as session:
        handler = CategoryCommandHandler(session)
        command = CreateCategoryCommand(name="Electronics", aggregate_id=category_id)
        await handler.handle_create_category(command)

    async with session_factory() as session:
        stmt = select(CategoryReadEntity).where(CategoryReadEntity.id == category_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert entity.name == "Electronics"


@pytest.mark.asyncio
async def test_inventory_layer_projector_create() -> None:
    """Test inventory layer creation is projected to the read model."""
    session_factory = make_session_factory()
    product_id = uuid4()
    inventory_id = uuid4()

    async with session_factory() as session:
        handler = InventoryCommandHandler(session)
        command = CreateInventoryLayerCommand(
            product_id=product_id,
            quantity_received=100,
            unit_cost=Decimal("10.00"),
            supplier_ref="SUP-001",
            aggregate_id=inventory_id,
        )
        await handler.handle_create_inventory_layer(command)

    async with session_factory() as session:
        stmt = select(InventoryLayerReadEntity).where(
            InventoryLayerReadEntity.id == inventory_id
        )
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert entity.quantity == 100


@pytest.mark.asyncio
async def test_draft_sale_projector_lifecycle() -> None:
    """Test full draft sale lifecycle: create then add items then finalize."""
    session_factory = make_session_factory()
    sale_id = uuid4()
    product_id_1 = uuid4()
    product_id_2 = uuid4()

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_create_draft_sale(
            CreateDraftSaleCommand(
                operator_id=uuid4(),
                session_id=uuid4(),
                aggregate_id=sale_id,
            )
        )

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_add_line_item(
            AddLineItemCommand(
                sale_id=sale_id,
                product_id=product_id_1,
                product_name="Item 1",
                unit_price=Decimal("25.00"),
                quantity=2,
                available_stock=10,
            )
        )

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_add_line_item(
            AddLineItemCommand(
                sale_id=sale_id,
                product_id=product_id_2,
                product_name="Item 2",
                unit_price=Decimal("15.00"),
                quantity=3,
                available_stock=20,
            )
        )

    async with session_factory() as session:
        stmt = select(DraftSaleReadEntity).where(DraftSaleReadEntity.id == sale_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert entity.status == "draft"
    line_items = json.loads(entity.line_items_json)
    assert len(line_items) == 2
    assert Decimal(str(entity.total_amount)) == Decimal("95.00")

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_finalize_sale(
            FinalizeSaleCommand(sale_id=sale_id, payment_method="cash")
        )

    async with session_factory() as session:
        stmt = select(DraftSaleReadEntity).where(DraftSaleReadEntity.id == sale_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert entity.status == "finalized"


@pytest.mark.asyncio
async def test_draft_sale_projector_remove_item() -> None:
    """Test removing a line item updates the read model."""
    session_factory = make_session_factory()
    sale_id = uuid4()
    product_id = uuid4()

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_create_draft_sale(
            CreateDraftSaleCommand(
                operator_id=uuid4(),
                session_id=uuid4(),
                aggregate_id=sale_id,
            )
        )

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_add_line_item(
            AddLineItemCommand(
                sale_id=sale_id,
                product_id=product_id,
                product_name="Item",
                unit_price=Decimal("20.00"),
                quantity=1,
                available_stock=10,
            )
        )

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_remove_line_item(
            RemoveLineItemCommand(sale_id=sale_id, product_id=product_id)
        )

    async with session_factory() as session:
        stmt = select(DraftSaleReadEntity).where(DraftSaleReadEntity.id == sale_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert len(json.loads(entity.line_items_json)) == 0
    assert float(entity.total_amount) == 0.0


@pytest.mark.asyncio
async def test_draft_sale_projector_void() -> None:
    """Test voiding a draft sale updates the read model status."""
    session_factory = make_session_factory()
    sale_id = uuid4()
    product_id = uuid4()

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_create_draft_sale(
            CreateDraftSaleCommand(
                operator_id=uuid4(),
                session_id=uuid4(),
                aggregate_id=sale_id,
            )
        )

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_add_line_item(
            AddLineItemCommand(
                sale_id=sale_id,
                product_id=product_id,
                product_name="Item",
                unit_price=Decimal("30.00"),
                quantity=1,
                available_stock=10,
            )
        )

    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_void_sale(
            VoidSaleCommand(sale_id=sale_id, reason="Customer changed mind")
        )

    async with session_factory() as session:
        stmt = select(DraftSaleReadEntity).where(DraftSaleReadEntity.id == sale_id)
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

    assert entity is not None
    assert entity.status == "voided"


@pytest.mark.asyncio
async def test_fifo_inventory_depletion() -> None:
    """
    FIFO depletion: create two inventory layers for the same product with
    different quantities, finalize a sale that spans both layers, and verify
    the oldest layer is depleted before the newer one.

    Setup:
      Layer A (oldest): 5 units
      Layer B (newer):  10 units
      Sale: 7 units  →  Layer A should reach 0, Layer B should lose 2 (8 remaining)
    """
    session_factory = make_session_factory()

    product_id = uuid4()
    layer_a_id = uuid4()
    layer_b_id = uuid4()
    sale_id = uuid4()

    # Create layer A (older — created first)
    async with session_factory() as session:
        handler = InventoryCommandHandler(session)
        await handler.handle_create_inventory_layer(
            CreateInventoryLayerCommand(
                product_id=product_id,
                quantity_received=5,
                unit_cost=Decimal("10.00"),
                supplier_ref="SUPPLIER-A",
                aggregate_id=layer_a_id,
            )
        )

    # Create layer B (newer)
    async with session_factory() as session:
        handler = InventoryCommandHandler(session)
        await handler.handle_create_inventory_layer(
            CreateInventoryLayerCommand(
                product_id=product_id,
                quantity_received=10,
                unit_cost=Decimal("12.00"),
                supplier_ref="SUPPLIER-B",
                aggregate_id=layer_b_id,
            )
        )

    # Create draft sale
    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_create_draft_sale(
            CreateDraftSaleCommand(
                operator_id=uuid4(),
                session_id=uuid4(),
                aggregate_id=sale_id,
            )
        )

    # Add 7 units of the product (spans both layers)
    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_add_line_item(
            AddLineItemCommand(
                sale_id=sale_id,
                product_id=product_id,
                product_name="Test Product",
                unit_price=Decimal("20.00"),
                quantity=7,
                available_stock=15,
            )
        )

    # Finalize — triggers FIFO depletion in DraftSaleProjector
    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_finalize_sale(
            FinalizeSaleCommand(sale_id=sale_id, payment_method="card")
        )

    # Verify layer quantities
    async with session_factory() as session:
        result_a = await session.execute(
            select(InventoryLayerReadEntity).where(InventoryLayerReadEntity.id == layer_a_id)
        )
        layer_a = result_a.scalar_one_or_none()

        result_b = await session.execute(
            select(InventoryLayerReadEntity).where(InventoryLayerReadEntity.id == layer_b_id)
        )
        layer_b = result_b.scalar_one_or_none()

    assert layer_a is not None, "Layer A read entity not found"
    assert layer_b is not None, "Layer B read entity not found"

    # Oldest layer fully depleted first
    assert layer_a.quantity == 0, f"Expected layer A qty=0, got {layer_a.quantity}"
    # Newer layer reduced by the remainder (7 - 5 = 2)
    assert layer_b.quantity == 8, f"Expected layer B qty=8, got {layer_b.quantity}"


@pytest.mark.asyncio
async def test_fifo_inventory_depletion() -> None:
    """
    FIFO depletion: two inventory layers for the same product.
    Sale spanning both layers should deplete the oldest first.

    Layer A (oldest): 5 units  →  should reach 0 after sale
    Layer B (newer):  10 units →  should lose 2 (remainder), ending at 8
    """
    session_factory = make_session_factory()

    product_id = uuid4()
    layer_a_id = uuid4()
    layer_b_id = uuid4()
    sale_id = uuid4()

    # Oldest layer
    async with session_factory() as session:
        handler = InventoryCommandHandler(session)
        await handler.handle_create_inventory_layer(
            CreateInventoryLayerCommand(
                product_id=product_id,
                quantity_received=5,
                unit_cost=Decimal("10.00"),
                supplier_ref="SUPPLIER-A",
                aggregate_id=layer_a_id,
            )
        )

    # Newer layer
    async with session_factory() as session:
        handler = InventoryCommandHandler(session)
        await handler.handle_create_inventory_layer(
            CreateInventoryLayerCommand(
                product_id=product_id,
                quantity_received=10,
                unit_cost=Decimal("12.00"),
                supplier_ref="SUPPLIER-B",
                aggregate_id=layer_b_id,
            )
        )

    # Draft sale
    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_create_draft_sale(
            CreateDraftSaleCommand(
                operator_id=uuid4(),
                session_id=uuid4(),
                aggregate_id=sale_id,
            )
        )

    # Add 7 units — spans both layers (5 from A, 2 from B)
    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_add_line_item(
            AddLineItemCommand(
                sale_id=sale_id,
                product_id=product_id,
                product_name="FIFO Product",
                unit_price=Decimal("20.00"),
                quantity=7,
                available_stock=15,
            )
        )

    # Finalize triggers FIFO depletion
    async with session_factory() as session:
        handler = SaleCommandHandler(session)
        await handler.handle_finalize_sale(
            FinalizeSaleCommand(sale_id=sale_id, payment_method="card")
        )

    # Assert oldest layer fully depleted, newer layer reduced by remainder
    async with session_factory() as session:
        result_a = await session.execute(
            select(InventoryLayerReadEntity).where(InventoryLayerReadEntity.id == layer_a_id)
        )
        layer_a = result_a.scalar_one_or_none()

        result_b = await session.execute(
            select(InventoryLayerReadEntity).where(InventoryLayerReadEntity.id == layer_b_id)
        )
        layer_b = result_b.scalar_one_or_none()

    assert layer_a is not None
    assert layer_b is not None
    assert layer_a.quantity == 0, f"Oldest layer should be fully depleted, got {layer_a.quantity}"
    assert layer_b.quantity == 8, f"Newer layer should have 8 remaining, got {layer_b.quantity}"
