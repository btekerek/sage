"""
Seed script — populates a fresh SAGE database with:
  · 3 users     (admin / manager / staff)
  · 7 categories
  · 51 products — a coherent bar menu
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
from app.infrastructure.models.user import UserModel
from app.infrastructure.projectors.read_entities import (
    CategoryReadEntity,
    DraftSaleReadEntity,
    InventoryLayerReadEntity,
    ProductReadEntity,
)

# ── Users ─────────────────────────────────────────────────────────────────────

USERS = [
    {"email": "admin@sage.com",   "password": "Admin123!",   "role": "admin"},
    {"email": "manager@sage.com", "password": "Manager123!", "role": "manager"},
    {"email": "staff@sage.com",   "password": "Staff123!",   "role": "staff"},
]

# ── Bar catalog ───────────────────────────────────────────────────────────────
#
# Tuple layout: (product_name, supplier_cost_Ft, opening_stock_units)
# Selling price is derived from the margin target (default 70 %):
#   selling = cost / (1 − margin)
#
# Cost reference at 70 % margin:
#   90 Ft → 300 Ft    120 Ft → 400 Ft    150 Ft → 500 Ft
#  180 Ft → 600 Ft    210 Ft → 700 Ft    240 Ft → 800 Ft
#  270 Ft → 900 Ft    300 Ft → 1 000 Ft  360 Ft → 1 200 Ft
#  420 Ft → 1 400 Ft  450 Ft → 1 500 Ft  600 Ft → 2 000 Ft
#  900 Ft → 3 000 Ft

CATALOG = [
    # ── Soft Drinks ──────────────────────────────────────────────────────────
    ("Soft Drinks", [
        ("Coca-Cola 0.33L can",       Decimal("120"),  140),
        ("Pepsi 0.33L can",           Decimal("120"),   90),
        ("Sprite 0.33L can",          Decimal("120"),   80),
        ("Fanta Orange 0.33L can",    Decimal("120"),   70),
        ("Mineral Water 0.5L",        Decimal("90"),   150),
        ("Sparkling Water 0.5L",      Decimal("90"),   100),
        ("Lemon Iced Tea 0.5L",       Decimal("150"),   60),
        ("Red Bull 0.25L",            Decimal("300"),   70),
        ("Tonic Water 0.2L",          Decimal("120"),   80),
        ("Ginger Beer 0.33L",         Decimal("150"),   45),
    ]),

    # ── Beer ─────────────────────────────────────────────────────────────────
    ("Beer", [
        ("Dreher Lager 0.5L",         Decimal("180"),  130),
        ("Soproni Ászok 0.5L",        Decimal("180"),  110),
        ("Heineken 0.33L",            Decimal("210"),   90),
        ("Staropramen 0.5L",          Decimal("210"),  100),
        ("Budweiser 0.33L",           Decimal("210"),   75),
        ("Hoegaarden Wheat 0.33L",    Decimal("240"),   55),
        ("Guinness 0.44L can",        Decimal("270"),   45),
        ("Craft IPA 0.33L",           Decimal("270"),   40),
    ]),

    # ── Wine & Sparkling ─────────────────────────────────────────────────────
    ("Wine & Sparkling", [
        ("House Red Wine 1.5dL",      Decimal("180"),   90),
        ("House White Wine 1.5dL",    Decimal("180"),   90),
        ("Rosé Wine 1.5dL",           Decimal("180"),   65),
        ("Prosecco 1.5dL",            Decimal("210"),   55),
        ("Cava Brut 1.5dL",           Decimal("210"),   40),
        ("Tokaji Furmint 0.75L",      Decimal("900"),   18),
        ("Egri Bikavér 0.75L",        Decimal("840"),   18),
        ("Chardonnay 0.75L",          Decimal("780"),   15),
    ]),

    # ── Spirits ──────────────────────────────────────────────────────────────
    ("Spirits", [
        ("Pálinka 0.5dL",             Decimal("300"),   65),
        ("Whiskey 0.4dL",             Decimal("360"),   45),
        ("Vodka 0.4dL",               Decimal("240"),   55),
        ("Rum 0.4dL",                 Decimal("240"),   50),
        ("Gin 0.4dL",                 Decimal("300"),   45),
        ("Jägermeister 0.4dL",        Decimal("270"),   40),
        ("Baileys 0.4dL",             Decimal("300"),   30),
        ("Tequila 0.4dL",             Decimal("270"),   35),
    ]),

    # ── Sweet Snacks ─────────────────────────────────────────────────────────
    ("Sweet Snacks", [
        ("Chocolate Bar 50g",         Decimal("120"),   55),
        ("Haribo Gummies 100g",       Decimal("135"),   50),
        ("Kinder Bueno",              Decimal("120"),   55),
        ("Snickers 50g",              Decimal("120"),   50),
        ("Milka 100g",                Decimal("150"),   40),
        ("Wafer Roll 50g",            Decimal("90"),    45),
        ("Bounty 57g",                Decimal("120"),   40),
    ]),

    # ── Salty Snacks ─────────────────────────────────────────────────────────
    ("Salty Snacks", [
        ("Potato Chips 100g",         Decimal("150"),   70),
        ("Pretzels 100g",             Decimal("120"),   60),
        ("Mixed Nuts 100g",           Decimal("210"),   50),
        ("Salted Peanuts 100g",       Decimal("120"),   60),
        ("Popcorn Salted 80g",        Decimal("120"),   45),
        ("Tortilla Chips 150g",       Decimal("150"),   40),
        ("Crackers 100g",             Decimal("120"),   45),
    ]),

    # ── Bar Food ─────────────────────────────────────────────────────────────
    ("Bar Food", [
        ("Hot Dog",                   Decimal("420"),   30),
        ("Grilled Sausage",           Decimal("510"),   25),
        ("French Fries 200g",         Decimal("360"),   35),
        ("Mozzarella Sticks 6pc",     Decimal("450"),   25),
        ("Chicken Wings 6pc",         Decimal("540"),   20),
        ("Ham & Cheese Toast",        Decimal("360"),   30),
        ("Onion Rings 200g",          Decimal("330"),   25),
    ]),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def wipe_all(session: AsyncSession) -> None:
    """Delete everything before re-seeding so the script is idempotent."""
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
    margin_target = Decimal(str(get_settings().margin_target))
    margin_divisor = Decimal("1") - margin_target  # e.g. 0.30 for 70 % margin

    total_products = 0
    for cat_name, products in CATALOG:
        cat_cmd = CreateCategoryCommand(name=cat_name)
        cat_handler = CategoryCommandHandler(session)
        await cat_handler.handle_create_category(cat_cmd)
        category_id: uuid.UUID = cat_cmd.aggregate_id  # type: ignore[assignment]
        print(f"\n  [{cat_name}]  ({len(products)} products)")

        for prod_name, cost, stock in products:
            selling_price = (cost / margin_divisor).quantize(Decimal("0.01"))

            prod_cmd = CreateProductCommand(
                name=prod_name,
                unit_price=selling_price,
                category_id=category_id,
            )
            prod_handler = ProductCommandHandler(session)
            await prod_handler.handle_create_product(prod_cmd)
            product_id: uuid.UUID = prod_cmd.aggregate_id  # type: ignore[assignment]

            inv_cmd = CreateInventoryLayerCommand(
                product_id=product_id,
                quantity_received=stock,
                unit_cost=cost,
                supplier_ref="SEED",
            )
            inv_handler = InventoryCommandHandler(session)
            await inv_handler.handle_create_inventory_layer(inv_cmd)

            print(f"    ✓  {prod_name:<35}  cost={cost} Ft  →  sell={selling_price} Ft  stock={stock}")
            total_products += 1

    print(f"\n  {total_products} products seeded across {len(CATALOG)} categories.")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://sage:sage@db:5432/sage_db",
    )
    engine = create_async_engine(database_url, echo=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("\n=== SAGE seed script — Bar Menu Edition ===\n")

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
