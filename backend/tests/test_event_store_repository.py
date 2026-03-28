import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import get_settings
from app.infrastructure.event_store.models import StoredEvent
from app.infrastructure.repositories.event_store_repository import EventStoreRepository


@pytest.mark.asyncio
async def test_append_and_load_stream_orders_by_sequence() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    aggregate_id = "test-aggregate-append-load"

    async with session_maker() as session:
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == aggregate_id)
        )
        await session.commit()

        repo = EventStoreRepository(session)

        first = await repo.append_event(
            aggregate_type="DraftSale",
            aggregate_id=aggregate_id,
            event_type="SaleInitialized",
            payload={"line_count": 0},
        )
        second = await repo.append_event(
            aggregate_type="DraftSale",
            aggregate_id=aggregate_id,
            event_type="LineItemAdded",
            payload={"sku": "ABC-123", "qty": 2},
        )
        await session.commit()

        stream = await repo.load_stream(aggregate_id)

        assert len(stream) == 2
        assert first.sequence_number == 1
        assert second.sequence_number == 2
        assert stream[0].event_type == "SaleInitialized"
        assert stream[1].event_type == "LineItemAdded"

    await engine.dispose()


@pytest.mark.asyncio
async def test_append_event_raises_on_expected_sequence_mismatch() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    aggregate_id = "test-aggregate-concurrency"

    async with session_maker() as session:
        await session.execute(
            delete(StoredEvent).where(StoredEvent.aggregate_id == aggregate_id)
        )
        await session.commit()

        repo = EventStoreRepository(session)

        await repo.append_event(
            aggregate_type="DraftSale",
            aggregate_id=aggregate_id,
            event_type="SaleInitialized",
            payload={"line_count": 0},
        )
        await session.commit()

        with pytest.raises(ValueError, match="Concurrency conflict"):
            await repo.append_event(
                aggregate_type="DraftSale",
                aggregate_id=aggregate_id,
                event_type="LineItemAdded",
                payload={"sku": "XYZ-999", "qty": 1},
                expected_sequence=0,
            )

    await engine.dispose()