from app.api.routes.categories import router as categories_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.products import router as products_router
from app.api.routes.sales import router as sales_router

__all__ = ["products_router", "categories_router", "inventory_router", "sales_router"]
