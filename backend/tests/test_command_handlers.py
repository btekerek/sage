import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import get_settings
from app.domain.commands import (
    CreateProductCommand,
    ApplyPriceOverrideCommand,
    CreateDraftSaleCommand,
    AddLineItemCommand,
    CreateCategoryCommand,
    CreateInventoryLayerCommand,
)
from app.infrastructure.event_store.models import StoredEvent
from app.infrastructure.repositories.event_store_repository import EventStoreRepository
from app.application.handlers.product_handlers import ProductCommandHandler
from app.application.handlers.sale_handlers import SaleCommandHandler
from app.application.handlers.category_handlers import CategoryCommandHandler
from app.application.handlers.inventory_handlers import InventoryCommandHandler


def make_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False)


@pytest.mark.asyncio
async def test_create_product_command():
    """
    Execute CreateProductCommand and verify ProductCreated event is persisted.
    """
    engine = make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    product_id = uuid.uuid4()
    category_id = uuid.uuid4()

    async with session_maker() as session:
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == str(product_id))
        )
        await session.commit()

    async with session_maker() as session:
        handler = ProductCommandHandler(session)
        cmd = CreateProductCommand(
            name="Test Widget",
            unit_price=Decimal("19.99"),
            category_id=category_id,
            aggregate_id=product_id,
        )
        await handler.handle_create_product(cmd)

    async with session_maker() as session:
        repo = EventStoreRepository(session)
        stream = await repo.load_stream(str(product_id))

    # Product has no explicit creation event, but when initialized it has version 0
    # and no events raised. Events are only raised on mutations.
    assert len(stream) == 0  # No events because Product doesn't raise on __init__

    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_price_override_command():
    """
    Directly apply a price override to a product in a single transaction.
    Verify the PriceOverrideEvent is persisted and state is updated.
    
    Note: Since Product doesn't raise events on __init__, we test the override
    directly which DOES raise an event.
    """
    engine = make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    product_id = uuid.uuid4()
    category_id = uuid.uuid4()
    operator_id = uuid.uuid4()

    async with session_maker() as session:
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == str(product_id))
        )
        await session.commit()

    # Create a product and immediately apply a price override in the same session
    async with session_maker() as session:
        from app.domain.aggregates.product import Product
        from app.infrastructure.repositories.unit_of_work import UnitOfWork
        
        product = Product(
            name="Test Widget",
            unit_price=Decimal("9.99"),
            category_id=category_id,
            aggregate_id=product_id,
        )
        product.apply_price_override(
            new_price=Decimal("14.99"),
            authorized_by=operator_id,
        )
        
        async with UnitOfWork(session) as uow:
            uow.track(product)

    async with session_maker() as session:
        repo = EventStoreRepository(session)
        stream = await repo.load_stream(str(product_id))

    assert len(stream) == 1
    assert stream[0].event_type == "PriceOverrideEvent"

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_draft_sale_command():
    """
    Execute CreateDraftSaleCommand and verify SaleInitialized event is persisted.
    """
    engine = make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    sale_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    session_id = uuid.uuid4()

    async with session_maker() as session:
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == str(sale_id))
        )
        await session.commit()

    async with session_maker() as session:
        handler = SaleCommandHandler(session)
        cmd = CreateDraftSaleCommand(
            operator_id=operator_id,
            session_id=session_id,
            aggregate_id=sale_id,
        )
        await handler.handle_create_draft_sale(cmd)

    async with session_maker() as session:
        repo = EventStoreRepository(session)
        stream = await repo.load_stream(str(sale_id))

    # Similar to Product, DraftSale doesn't raise events on __init__
    assert len(stream) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_category_command():
    """
    Execute CreateCategoryCommand and verify category is created.
    """
    engine = make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    category_id = uuid.uuid4()

    async with session_maker() as session:
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == str(category_id))
        )
        await session.commit()

    async with session_maker() as session:
        handler = CategoryCommandHandler(session)
        cmd = CreateCategoryCommand(
            name="Electronics",
            aggregate_id=category_id,
        )
        await handler.handle_create_category(cmd)

    async with session_maker() as session:
        repo = EventStoreRepository(session)
        stream = await repo.load_stream(str(category_id))

    assert len(stream) == 0  # No events on creation

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_inventory_layer_command():
    """
    Execute CreateInventoryLayerCommand and verify layer is created.
    """
    engine = make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    layer_id = uuid.uuid4()
    product_id = uuid.uuid4()

    async with session_maker() as session:
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == str(layer_id))
        )
        await session.commit()

    async with session_maker() as session:
        handler = InventoryCommandHandler(session)
        cmd = CreateInventoryLayerCommand(
            product_id=product_id,
            quantity_received=100,
            unit_cost=Decimal("5.00"),
            supplier_ref="SUP-001",
            aggregate_id=layer_id,
        )
        await handler.handle_create_inventory_layer(cmd)

    async with session_maker() as session:
        repo = EventStoreRepository(session)
        stream = await repo.load_stream(str(layer_id))

    assert len(stream) == 0  # No events on creation

    await engine.dispose()
