from contextlib import asynccontextmanager

from app.api.routes.categories import router as categories_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.products import router as products_router
from app.core.db import close_db, init_db, setup_session_maker
from fastapi import FastAPI


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

app.include_router(products_router)
app.include_router(categories_router)
app.include_router(inventory_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
