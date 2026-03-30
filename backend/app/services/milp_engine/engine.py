"""
MILP Replenishment Optimisation Engine.

Implements the exact formulation from the thesis (section 3.1.8):

Decision variable:
    x_i ∈ Z+  — order quantity for product i

Objective:
    Minimise Σ c_i * x_i  (total procurement cost)

Subject to:
    Budget:    Σ c_i * x_i <= B
    Coverage:  s_i + x_i >= d_i * (l_i + T)   for all i
    MOQ:       x_i >= m_i                        if x_i > 0
    Integer:   x_i ∈ Z+

If the budget constraint makes the full solution infeasible, falls back to
the two-phase priority heuristic described in the thesis:
    Phase 1 — rank products by r_i = s_i / d_i (ascending, closest to stockout first)
    Phase 2 — add products one by one until budget would be exceeded
"""

import logging
from decimal import Decimal

import pulp  # type: ignore[import-untyped]

from .models import (
    ProductReplenishmentInput,
    ReplenishmentResult,
    ReplenishmentSuggestion,
)

logger = logging.getLogger(__name__)

_DAYS_REMAINING_CRITICAL = 3
_DAYS_REMAINING_LOW = 7


def run_milp(
    products: list[ProductReplenishmentInput],
    budget: float,
    target_coverage_days: int,
) -> ReplenishmentResult:
    """
    Run the MILP solver over all candidate products.
    Returns a ReplenishmentResult with suggestions ordered by urgency.
    """
    if not products:
        return ReplenishmentResult(
            suggestions=[],
            total_estimated_cost=Decimal("0.00"),
            budget_used=Decimal("0.00"),
            budget_remaining=Decimal(str(budget)),
            feasible=True,
            solver_status="no_candidates",
        )

    # Filter out products with zero demand — can't compute coverage for them
    candidates = [p for p in products if p.daily_demand > Decimal("0")]
    if not candidates:
        return ReplenishmentResult(
            suggestions=[],
            total_estimated_cost=Decimal("0.00"),
            budget_used=Decimal("0.00"),
            budget_remaining=Decimal(str(budget)),
            feasible=True,
            solver_status="no_demand_data",
        )

    result, status = _solve(candidates, budget, target_coverage_days)

    if status == "Infeasible":
        logger.info("Full MILP infeasible — falling back to priority heuristic")
        result, status = _priority_heuristic(candidates, budget, target_coverage_days)

    suggestions = _build_suggestions(candidates, result)
    total_cost = sum(s.estimated_cost for s in suggestions)
    budget_decimal = Decimal(str(budget)).quantize(Decimal("0.01"))

    return ReplenishmentResult(
        suggestions=suggestions,
        total_estimated_cost=total_cost,
        budget_used=total_cost,
        budget_remaining=budget_decimal - total_cost,
        feasible=status not in ("Infeasible", "Not Solved"),
        solver_status=status,
    )


def _solve(
    candidates: list[ProductReplenishmentInput],
    budget: float,
    target_days: int,
) -> tuple[dict[str, int], str]:
    """Run the full MILP problem. Returns (order_quantities, solver_status)."""
    prob = pulp.LpProblem("replenishment", pulp.LpMinimize)

    # Decision variables: x_i >= 0, integer
    x = {
        p.product_id: pulp.LpVariable(f"x_{p.product_id}", lowBound=0, cat="Integer")
        for p in candidates
    }

    # Objective: minimise total cost
    prob += pulp.lpSum(float(p.unit_cost) * x[p.product_id] for p in candidates)

    # Budget constraint
    prob += (
        pulp.lpSum(float(p.unit_cost) * x[p.product_id] for p in candidates) <= budget
    )

    # Coverage constraint: s_i + x_i >= d_i * (l_i + T)
    for p in candidates:
        required = float(p.daily_demand) * (p.lead_time_days + target_days)
        prob += p.current_stock + x[p.product_id] >= required

    # MOQ constraint: if ordering, order at least min_order_quantity
    # Modelled as: x_i >= m_i * y_i where y_i is binary "are we ordering?"
    y = {
        p.product_id: pulp.LpVariable(f"y_{p.product_id}", cat="Binary")
        for p in candidates
    }
    for p in candidates:
        prob += x[p.product_id] >= p.min_order_quantity * y[p.product_id]
        # Big-M to link x and y: x_i <= M * y_i
        big_m = int(float(p.daily_demand) * (p.lead_time_days + target_days) * 10) + 1
        prob += x[p.product_id] <= big_m * y[p.product_id]

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]

    order_quantities = {
        p.product_id: max(0, int(round(pulp.value(x[p.product_id]) or 0)))
        for p in candidates
    }

    return order_quantities, status


def _priority_heuristic(
    candidates: list[ProductReplenishmentInput],
    budget: float,
    target_days: int,
) -> tuple[dict[str, int], str]:
    """
    Two-phase fallback heuristic when budget is too tight for full coverage.

    Phase 1: rank by r_i = s_i / d_i (days of stock remaining, ascending)
    Phase 2: solve MILP for growing candidate subsets until budget is exceeded
    """
    # Phase 1: rank by urgency
    ranked = sorted(
        candidates,
        key=lambda p: float(p.current_stock) / float(p.daily_demand),
    )

    # Phase 2: iteratively add products
    best_result: dict = {p.product_id: 0 for p in candidates}
    best_status = "Heuristic"

    for i in range(1, len(ranked) + 1):
        subset = ranked[:i]
        result, status = _solve(subset, budget, target_days)
        if status == "Infeasible":
            break
        best_result = result
        best_status = f"Heuristic({i}/{len(ranked)})"

    return best_result, best_status


def _build_suggestions(
    candidates: list[ProductReplenishmentInput],
    order_quantities: dict,
) -> list[ReplenishmentSuggestion]:
    """Convert solver output into ReplenishmentSuggestion objects."""
    suggestions = []

    for p in candidates:
        qty = order_quantities.get(p.product_id, 0)
        if qty <= 0:
            continue

        days_remaining = (
            Decimal(str(p.current_stock)) / p.daily_demand
            if p.daily_demand > 0
            else Decimal("999")
        ).quantize(Decimal("0.1"))

        if days_remaining <= _DAYS_REMAINING_CRITICAL:
            priority = "critical"
        elif days_remaining <= _DAYS_REMAINING_LOW:
            priority = "low"
        else:
            priority = "ok"

        suggestions.append(
            ReplenishmentSuggestion(
                product_id=p.product_id,
                product_name=p.product_name,
                current_stock=p.current_stock,
                daily_demand=p.daily_demand,
                days_of_stock_remaining=days_remaining,
                suggested_order_quantity=qty,
                estimated_cost=(p.unit_cost * qty).quantize(Decimal("0.01")),
                priority=priority,
            )
        )

    # Sort by urgency: critical first, then by days remaining ascending
    suggestions.sort(
        key=lambda s: (s.priority != "critical", s.days_of_stock_remaining)
    )
    return suggestions
