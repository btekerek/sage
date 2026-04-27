from contextlib import asynccontextmanager

from app.api.routes.auth import router as auth_router
from app.api.routes.categories import router as categories_router
from app.api.routes.config import router as config_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.inventory_mgmt import router as inventory_mgmt_router
from app.api.routes.invoices import router as invoices_router
from app.api.routes.products import router as products_router
from app.api.routes.replenishment import router as replenishment_router
from app.api.routes.replay import router as replay_router
from app.api.routes.sales import router as sales_router
from app.api.routes.users import router as users_router
from app.core.db import close_db, init_db, setup_session_maker
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await setup_session_maker()
    yield
    await close_db()


app = FastAPI(
    title="SAGE — Sales, Availability and Growth/Insights Engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(config_router)
app.include_router(users_router)
app.include_router(products_router)
app.include_router(categories_router)
app.include_router(inventory_router)
app.include_router(inventory_mgmt_router)
app.include_router(sales_router)
app.include_router(invoices_router)
app.include_router(replenishment_router)
app.include_router(replay_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
