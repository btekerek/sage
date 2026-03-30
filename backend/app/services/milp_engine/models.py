"""Data models for the MILP replenishment engine."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ProductReplenishmentInput(BaseModel):
    product_id: UUID
    product_name: str
    current_stock: int
    daily_demand: Decimal
    unit_cost: Decimal
    lead_time_days: int = 3
    min_order_quantity: int = 1


class ReplenishmentSuggestion(BaseModel):
    product_id: UUID
    product_name: str
    current_stock: int
    daily_demand: Decimal
    days_of_stock_remaining: Decimal
    suggested_order_quantity: int
    estimated_cost: Decimal
    priority: str


class ReplenishmentResult(BaseModel):
    suggestions: list[ReplenishmentSuggestion]
    total_estimated_cost: Decimal
    budget_used: Decimal
    budget_remaining: Decimal
    feasible: bool
    solver_status: str