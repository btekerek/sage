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
from app.core.settings import get_settings
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
    {"email": "admin@sage.com",   "password": "Admin123!",   "role": "admin"},
    {"email": "manager@sage.com", "password": "Manager123!", "role": "manager"},
    {"email": "staff@sage.com",   "password": "Staff123!",   "role": "staff"},
]

# (category_name, [(product_name, supplier_cost, opening_stock), ...])
# supplier_cost = what we pay for one unit; selling price is derived from the margin target.
CATALOG = [
    ("Beverages", [
        ("Mineral Water 0.5L",  Decimal("60"),   50),
        ("Orange Juice 1L",     Decimal("180"),  30),
        ("Cola 0.33L",          Decimal("105"),  40),
    ]),
    ("Snacks", [
        ("Potato Chips 100g",   Decimal("135"),  25),
        ("Chocolate Bar 50g",   Decimal("90"),   35),
        ("Mixed Nuts 200g",     Decimal("270"),  20),
    ]),
    ("Dairy", [
        ("Full-Fat Milk 1L",    Decimal("120"),  20),
        ("Greek Yogurt 150g",   Decimal("105"),  15),
        ("Butter 250g",         Decimal("210"),  12),
    ]),
    ("Bakery", [
        ("White Bread Loaf",    Decimal("165"),  10),
        ("Croissant",           Decimal("90"),   18),
        ("Whole-Grain Roll",    Decimal("60"),   22),
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
    # Read margin target from settings so the seed always matches the configured default.
    margin_target = Decimal(str(get_settings().margin_target))
    margin_divisor = Decimal("1") - margin_target   # e.g. 0.30 for 70 % margin

    for cat_name, products in CATALOG:
        # ── category ──────────────────────────────────────────────────────────
        cat_cmd = CreateCategoryCommand(name=cat_name)
        cat_handler = CategoryCommandHandler(session)
        await cat_handler.handle_create_category(cat_cmd)
        category_id: uuid.UUID = cat_cmd.aggregate_id  # type: ignore[assignment]
        print(f"\n  [category] {cat_name}  ({category_id})")

        for prod_name, cost, stock in products:
            # selling_price = cost / (1 − margin_target)
            # e.g. cost=60 Ft, margin=70% → selling=200 Ft
            selling_price = (cost / margin_divisor).quantize(Decimal("0.01"))

            # ── product ───────────────────────────────────────────────────────
            prod_cmd = CreateProductCommand(
                name=prod_name,
                unit_price=selling_price,
                category_id=category_id,
            )
            prod_handler = ProductCommandHandler(session)
            await prod_handler.handle_create_product(prod_cmd)
            product_id: uuid.UUID = prod_cmd.aggregate_id  # type: ignore[assignment]
            print(f"    ✓ product '{prod_name}'  cost={cost} Ft → selling={selling_price} Ft")

            # ── opening stock (unit_cost = actual purchase cost) ──────────────
            inv_cmd = CreateInventoryLayerCommand(
                product_id=product_id,
                quantity_received=stock,
                unit_cost=cost,
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
