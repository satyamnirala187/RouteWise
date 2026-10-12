"""Matrix request-volume and cost projection (acceptance criterion 11).

Prices: Google Maps Platform global price list, USD, page last updated
2026-10-08 UTC, read 2026-10-12. Re-check before any spending decision.
TWO_WHEELER travel mode bills as Compute Route Matrix *Enterprise*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# (free elements per month, [(upper bound of tier in monthly elements, USD per 1000)])
SKUS = {
    "Enterprise (TWO_WHEELER)": (1_000, [(100_000, 15.00), (500_000, 12.00), (1_000_000, 9.00), (5_000_000, 4.50), (math.inf, 1.14)]),
    "Pro (traffic-aware)": (5_000, [(100_000, 10.00), (500_000, 8.00), (1_000_000, 6.00), (5_000_000, 3.00), (math.inf, 0.75)]),
    "Essentials (DRIVE, basic)": (10_000, [(100_000, 5.00), (500_000, 4.00), (1_000_000, 3.00), (5_000_000, 1.50), (math.inf, 0.38)]),
}
MAX_ELEMENTS_PER_REQUEST = 625


def monthly_cost_usd(elements: int, sku: str) -> float:
    free, tiers = SKUS[sku]
    cost, lower = 0.0, free
    for upper, per_1000 in tiers:
        if elements <= lower:
            break
        billable = min(elements, upper) - lower
        cost += billable / 1000 * per_1000
        lower = upper
    return round(cost, 2)


@dataclass
class Projection:
    orders: int
    riders: int
    locations: int
    initial_elements: int
    initial_requests: int
    reroute_elements_no_reuse: int
    reroute_elements_with_reuse: int
    per_round_no_reuse: int
    per_round_with_reuse: int


def project(orders: int, riders: int, reroutes_per_rider: int = 2) -> Projection:
    """Upper-bound element counts for one round.

    locations = orders + 2 starts (Office, Warehouse) + one distinct fixed end per
    rider (worst case; shared or Last-stop endpoints reduce it). Elements are
    origins x destinations, diagonal included, because that is what is billed.
    A reroute solves origin + remaining stops + end. "With reuse" only requests the
    new origin row, which is only possible if the provider terms allow keeping the
    initial matrix for the round (Google: restricted, see PROVIDER-EVALUATION.md).
    """
    loc = orders + 2 + riders
    initial = loc * loc
    tile = int(math.sqrt(MAX_ELEMENTS_PER_REQUEST))
    requests = math.ceil(loc / tile) ** 2
    remaining = math.ceil(orders / riders / 2)
    no_reuse = (remaining + 2) ** 2
    with_reuse = remaining + 1
    n = riders * reroutes_per_rider
    return Projection(orders, riders, loc, initial, requests, no_reuse, with_reuse,
                      initial + n * no_reuse, initial + n * with_reuse)


SIZES = [(20, 3), (50, 5), (100, 8)]
ROUNDS_PER_MONTH = 26  # one round per working day, six days a week (assumption)


def projection_table() -> str:
    rows = [
        "| Orders | Riders | Locations | Initial elements (requests) | Per round, no reuse | Per round, origin-row reuse | Monthly elements (no reuse) | "
        + " | ".join(f"{s} USD/month" for s in SKUS) + " |",
        "|" + "---|" * (7 + len(SKUS)),
    ]
    for orders, riders in SIZES:
        p = project(orders, riders)
        monthly = p.per_round_no_reuse * ROUNDS_PER_MONTH
        costs = " | ".join(f"{monthly_cost_usd(monthly, s):,.2f}" for s in SKUS)
        rows.append(
            f"| {orders} | {riders} | {p.locations} | {p.initial_elements:,} ({p.initial_requests}) | "
            f"{p.per_round_no_reuse:,} | {p.per_round_with_reuse:,} | {monthly:,} | {costs} |"
        )
    return "\n".join(rows)
