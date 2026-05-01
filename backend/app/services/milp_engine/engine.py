"""
MILP Replenishment Optimisation Engine.

Formulation (section 3.1.8 of thesis):

Parameters:
    d_i   -- daily demand (units/day)
    s_i   -- current stock (units)
    c_i   -- unit procurement cost (HUF)
    l_i   -- supplier lead time (days)          [per-product or global default]
    T_i   -- target coverage horizon (days)     [per-product or global default]
    m_i   -- minimum order quantity (MOQ)
    B     -- weekly purchasing budget (HUF)
    r_i   = max(0, ceil(d_i * (l_i + T_i) - s_i))  required order to reach target
    w_i   = 1 / max(s_i / d_i, 0.5)                urgency weight (higher = more critical)

Decision variables:
    x_i in Z+        order quantity for product i
    y_i in {0,1}     1 if product i is ordered at all (MOQ enforcement)
    z_i in Z+        coverage shortfall = max(0, r_i - x_i)

Objective:
    minimise  sum w_i * z_i          (weighted coverage shortfall)

Subject to:
    Budget:    sum c_i * x_i  <= B                          (cross-product coupling)
    Shortfall: z_i  >= r_i - x_i        for all i           (shortfall accounting)
    MOQ-link:  x_i  >= m_i * y_i        for all i           (minimum order size)
    Big-M:     x_i  <= M_i * y_i        for all i           (y_i = 0 => x_i = 0)
    Domain:    x_i, z_i in Z+,  y_i in {0,1}

Properties:
  * When B >= sum c_i * r_i (budget non-binding): all z_i = 0, x_i = r_i for every
    product -- identical to the unconstrained closed-form solution.
  * When B < sum c_i * r_i (budget binding): the solver must allocate limited spend
    across products.  The urgency weights w_i = 1/days_remaining ensure that
    near-stockout products absorb budget first, yielding a triage ordering that
    cannot be decomposed into per-product sub-problems.  This is a variant of the
    bounded integer knapsack problem (NP-hard), making the MILP formulation
    non-trivially justified.
  * l_i and T_i are resolved per-product: each ProductReplenishmentInput may carry
    its own lead_time_days and target_coverage_days; None falls back to the global
    target_coverage_days passed to run_milp.
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


def _effective_target(p: ProductReplenishmentInput, global_target: int) -> int:
    """Return per-product target coverage days, falling back to global default."""
    return p.target_coverage_days if p.target_coverage_days is not None else global_target


def run_milp(
    products: list[ProductReplenishmentInput],
    target_coverage_days: int,
    weekly_budget: Decimal,
) -> ReplenishmentResult:
    if not products:
        return ReplenishmentResult(
            suggestions=[],
            total_estimated_cost=Decimal("0.00"),
            feasible=True,
            solver_status="no_candidates",
            budget=weekly_budget,
            budget_used=Decimal("0.00"),
            budget_constrained=False,
        )

    candidates = [p for p in products if p.daily_demand > Decimal("0")]
    if not candidates:
        return ReplenishmentResult(
            suggestions=[],
            total_estimated_cost=Decimal("0.00"),
            feasible=True,
            solver_status="no_demand_data",
            budget=weekly_budget,
            budget_used=Decimal("0.00"),
            budget_constrained=False,
        )

    needs_replenishment = [
        p for p in candidates
        if p.current_stock < float(p.daily_demand) * (
            p.lead_time_days + _effective_target(p, target_coverage_days)
        )
    ]

    if not needs_replenishment:
        return ReplenishmentResult(
            suggestions=[],
            total_estimated_cost=Decimal("0.00"),
            feasible=True,
            solver_status="Optimal",
            budget=weekly_budget,
            budget_used=Decimal("0.00"),
            budget_constrained=False,
        )

    order_quantities, status = _solve(needs_replenishment, target_coverage_days, weekly_budget)
    suggestions = _build_suggestions(needs_replenishment, order_quantities, target_coverage_days)
    total_cost = sum(s.estimated_cost for s in suggestions)

    budget_constrained = any(s.coverage_fraction < Decimal("1.00") for s in suggestions)

    return ReplenishmentResult(
        suggestions=suggestions,
        total_estimated_cost=total_cost,
        feasible=True,
        solver_status=status,
        budget=weekly_budget,
        budget_used=total_cost,
        budget_constrained=budget_constrained,
    )


def _solve(
    candidates: list[ProductReplenishmentInput],
    global_target_days: int,
    weekly_budget: Decimal,
) -> tuple[dict, str]:
    prob = pulp.LpProblem("replenishment", pulp.LpMinimize)

    x = {
        p.product_id: pulp.LpVariable(f"x_{p.product_id}", lowBound=0, cat="Integer")
        for p in candidates
    }
    y = {
        p.product_id: pulp.LpVariable(f"y_{p.product_id}", cat="Binary")
        for p in candidates
    }
    z = {
        p.product_id: pulp.LpVariable(f"z_{p.product_id}", lowBound=0, cat="Integer")
        for p in candidates
    }

    weights = {}
    for p in candidates:
        days_remaining = (
            float(p.current_stock) / float(p.daily_demand)
            if p.daily_demand > 0
            else 999.0
        )
        weights[p.product_id] = 1.0 / max(days_remaining, 0.5)

    prob += pulp.lpSum(weights[p.product_id] * z[p.product_id] for p in candidates)

    prob += (
        pulp.lpSum(float(p.unit_cost) * x[p.product_id] for p in candidates)
        <= float(weekly_budget)
    )

    for p in candidates:
        t = _effective_target(p, global_target_days)
        required = float(p.daily_demand) * (p.lead_time_days + t)
        shortage = max(0.0, required - p.current_stock)
        prob += z[p.product_id] >= shortage - x[p.product_id]

    for p in candidates:
        t = _effective_target(p, global_target_days)
        required = float(p.daily_demand) * (p.lead_time_days + t)
        big_m = int(required * 10) + 1
        prob += x[p.product_id] >= p.min_order_quantity * y[p.product_id]
        prob += x[p.product_id] <= big_m * y[p.product_id]

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]

    order_quantities = {
        p.product_id: max(0, int(round(pulp.value(x[p.product_id]) or 0)))
        for p in candidates
    }
    return order_quantities, status


def _build_suggestions(
    candidates: list[ProductReplenishmentInput],
    order_quantities: dict,
    global_target_days: int,
) -> list[ReplenishmentSuggestion]:
    suggestions = []

    for p in candidates:
        qty = order_quantities.get(p.product_id, 0)
        if qty <= 0:
            continue

        t = _effective_target(p, global_target_days)

        days_remaining = (
            Decimal(str(p.current_stock)) / p.daily_demand
            if p.daily_demand > 0
            else Decimal("999")
        ).quantize(Decimal("0.1"))

        required = max(
            0,
            int((float(p.daily_demand) * (p.lead_time_days + t)) - p.current_stock)
        )
        coverage_fraction = (
            Decimal(str(min(qty, required))) / Decimal(str(required))
            if required > 0
            else Decimal("1.00")
        ).quantize(Decimal("0.01"))

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
                coverage_fraction=coverage_fraction,
            )
        )

    suggestions.sort(
        key=lambda s: (s.priority != "critical", s.days_of_stock_remaining)
    )
    return suggestions
