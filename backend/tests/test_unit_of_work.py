# mypy: disable-error-code=import-not-found
# pyright: reportMissingImports=false
import uuid
from decimal import Decimal

import pytest
from app.core.settings import get_settings
from app.domain.aggregates.product import Product
from app.infrastructure.event_store.models import StoredEvent
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.unit_of_work import UnitOfWork
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def make_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False)


@pytest.mark.asyncio
async def test_uow_persists_pending_events() -> None:
    """
    Raise a PriceOverrideEvent on a Product, track it in UoW, commit,
    then verify the event is saved in the events table.
    """
    engine = make_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    product_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    category_id = uuid.uuid4()

    async with session_maker() as session:
        # Clean up any leftover rows from previous runs
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == str(product_id))
        )
        await session.commit()

    async with session_maker() as session:
        product = Product(
            name="Widget A",
            unit_price=Decimal("9.99"),
            category_id=category_id,
            aggregate_id=product_id,
        )
        product.apply_price_override(
            new_price=Decimal("12.99"),
            authorized_by=operator_id,
        )

        async with UnitOfWork(session) as uow:
            uow.track(product)
        # UoW commits on clean exit

    async with session_maker() as session:
        from app.infrastructure.repositories.event_store_repository import (
            EventStoreRepository,
        )

        repo = EventStoreRepository(session)
        stream = await repo.load_stream(str(product_id))

    assert len(stream) == 2
    assert stream[0].event_type == "ProductCreatedEvent"
    assert stream[1].event_type == "PriceOverrideEvent"
    assert stream[0].aggregate_type == "Product"

    await engine.dispose()


@pytest.mark.asyncio
async def test_product_repository_reconstructs_state() -> None:
    """
    Save a PriceOverrideEvent via UoW, then reload the Product via
    ProductRepository and verify the new price was applied.
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

    # Persist a price override event
    async with session_maker() as session:
        from app.infrastructure.repositories.event_store_repository import (
            EventStoreRepository,
        )

        repo = EventStoreRepository(session)
        await repo.append_event(
            aggregate_type="Product",
            aggregate_id=str(product_id),
            event_type="PriceOverrideEvent",
            payload={
                "product_id": str(product_id),
                "previous_price": "9.99",
                "new_price": "14.99",
                "authorized_by": str(operator_id),
            },
        )
        await session.commit()

    # Reconstruct via repository
    async with session_maker() as session:
        product_repo = ProductRepository(session)
        product = await product_repo.get(product_id)

    assert product is not None
    assert product.unit_price == Decimal("14.99")
    assert product.version == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_uow_rolls_back_on_exception() -> None:
    """
    If an exception is raised inside the UoW block, no events are committed.
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

    try:
        async with session_maker() as session:
            product = Product(
                name="Doomed Product",
                unit_price=Decimal("5.00"),
                category_id=category_id,
                aggregate_id=product_id,
            )
            product.apply_price_override(
                new_price=Decimal("7.00"),
                authorized_by=uuid.uuid4(),
            )
            async with UnitOfWork(session) as uow:
                uow.track(product)
                raise RuntimeError("simulated failure")
    except RuntimeError:
        pass

    async with session_maker() as session:
        from app.infrastructure.repositories.event_store_repository import (
            EventStoreRepository,
        )

        repo = EventStoreRepository(session)
        stream = await repo.load_stream(str(product_id))

    assert stream == [], "Events must not be persisted when UoW rolls back"

    await engine.dispose()
