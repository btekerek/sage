"""
Seed script — populates a fresh SAGE database with:
  · 3 users   (admin / manager / staff)
  · 4 categories
  · 12 products (3 per category)
  · opening stock for every product

Run inside the backend container:
    docker compose exec backend python seed.py
"""

import asyncio
import os
import uuid
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.application.handlers.category_handlers import CategoryCommandHandler
from app.application.handlers.inventory_handlers import InventoryCommandHandler
from app.application.handlers.product_handlers import ProductCommandHandler
from app.core.security import hash_password
from app.domain.commands.category_commands import CreateCategoryCommand
from app.domain.commands.inventory_commands import CreateInventoryLayerCommand
from app.domain.commands.product_commands import CreateProductCommand
from app.infrastructure.event_store.models import StoredEvent
from app.infrastructure.models.user import UserBase, UserModel
from app.infrastructure.projectors.read_entities import (
    CategoryReadEntity,
    DraftSaleReadEntity,
    InventoryLayerReadEntity,
    ProductReadEntity,
)

# ── Data ──────────────────────────────────────────────────────────────────────

USERS = [
    {"email": "admin@sage.com",   "password": "admin123",   "role": "admin"},
    {"email": "manager@sage.com", "password": "manager123", "role": "manager"},
    {"email": "staff@sage.com",   "password": "staff123",   "role": "staff"},
]

# (category_name, [(product_name, unit_price, opening_stock), ...])
CATALOG = [
    ("Beverages", [
        ("Mineral Water 0.5L",  Decimal("199"),  50),
        ("Orange Juice 1L",     Decimal("599"),  30),
        ("Cola 0.33L",          Decimal("349"),  40),
    ]),
    ("Snacks", [
        ("Potato Chips 100g",   Decimal("449"),  25),
        ("Chocolate Bar 50g",   Decimal("299"),  35),
        ("Mixed Nuts 200g",     Decimal("899"),  20),
    ]),
    ("Dairy", [
        ("Full-Fat Milk 1L",    Decimal("399"),  20),
        ("Greek Yogurt 150g",   Decimal("349"),  15),
        ("Butter 250g",         Decimal("699"),  12),
    ]),
    ("Bakery", [
        ("White Bread Loaf",    Decimal("549"),  10),
        ("Croissant",           Decimal("299"),  18),
        ("Whole-Grain Roll",    Decimal("199"),  22),
    ]),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def wipe_all(session: AsyncSession) -> None:
    """
    Delete everything before re-seeding so the script is idempotent.
    Order matters: read-model tables first, then the event store.
    """
    await session.execute(delete(DraftSaleReadEntity))
    await session.execute(delete(InventoryLayerReadEntity))
    await session.execute(delete(ProductReadEntity))
    await session.execute(delete(CategoryReadEntity))
    await session.execute(delete(UserModel))
    await session.execute(delete(StoredEvent))
    await session.commit()
    print("  ✓ all tables wiped\n")


async def seed_users(session: AsyncSession) -> None:
    for u in USERS:
        session.add(
            UserModel(
                id=str(uuid.uuid4()),
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                role=u["role"],
                is_active=True,
            )
        )
        print(f"  ✓ {u['email']} ({u['role']})")
    await session.commit()


async def seed_catalog(session: AsyncSession) -> None:
    admin_id = uuid.uuid4()   # synthetic authorizer UUID for price commands

    for cat_name, products in CATALOG:
        # ── category ──────────────────────────────────────────────────────────
        cat_cmd = CreateCategoryCommand(name=cat_name)
        cat_handler = CategoryCommandHandler(session)
        await cat_handler.handle_create_category(cat_cmd)
        category_id: uuid.UUID = cat_cmd.aggregate_id  # type: ignore[assignment]
        print(f"\n  [category] {cat_name}  ({category_id})")

        for prod_name, price, stock in products:
            # ── product ───────────────────────────────────────────────────────
            prod_cmd = CreateProductCommand(
                name=prod_name,
                unit_price=price,
                category_id=category_id,
            )
            prod_handler = ProductCommandHandler(session)
            await prod_handler.handle_create_product(prod_cmd)
            product_id: uuid.UUID = prod_cmd.aggregate_id  # type: ignore[assignment]
            print(f"    ✓ product '{prod_name}'  price={price} Ft")

            # ── opening stock ─────────────────────────────────────────────────
            inv_cmd = CreateInventoryLayerCommand(
                product_id=product_id,
                quantity_received=stock,
                unit_cost=price * Decimal("0.6"),   # 40 % margin assumption
                supplier_ref="SEED",
            )
            inv_handler = InventoryCommandHandler(session)
            await inv_handler.handle_create_inventory_layer(inv_cmd)
            print(f"      ↳ stock: {stock} units")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    # Read directly from the environment so the Docker-injected DATABASE_URL
    # is used even if a local .env file has a different (localhost) URL.
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://sage:sage@db:5432/sage_db",
    )
    engine = create_async_engine(database_url, echo=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("\n=== SAGE seed script ===\n")

    async with maker() as session:
        print("── Wiping existing data ──")
        await wipe_all(session)

    async with maker() as session:
        print("── Users ──")
        await seed_users(session)

    async with maker() as session:
        print("\n── Catalog ──")
        await seed_catalog(session)

    await engine.dispose()
    print("\n✅  Seed complete.\n")


if __name__ == "__main__":
    asyncio.run(main())
