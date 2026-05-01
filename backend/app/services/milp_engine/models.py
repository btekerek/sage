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
    # None = use the global target_coverage_days passed to run_milp
    target_coverage_days: int | None = None


class ReplenishmentSuggestion(BaseModel):
    product_id: UUID
    product_name: str
    current_stock: int
    daily_demand: Decimal
    days_of_stock_remaining: Decimal
    suggested_order_quantity: int
    estimated_cost: Decimal
    priority: str
    coverage_fraction: Decimal


class ReplenishmentResult(BaseModel):
    suggestions: list[ReplenishmentSuggestion]
    total_estimated_cost: Decimal
    feasible: bool
    solver_status: str
    budget: Decimal
    budget_used: Decimal
    budget_constrained: bool
