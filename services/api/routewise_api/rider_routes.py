"""Step 4B: a rider's EFFECTIVE route in a round, shared by the rider and admin read paths so they
can never disagree.

The round's current plan (`route_plans`, `plan_routes`, `plan_orders`) is immutable. A rider's
own recalculation is a `route_revisions` row layered on that plan. The effective route is the
rider's current revision for the CURRENT plan if there is one, otherwise their plan route.
Revisions of an older plan are never effective (a newer round plan supersedes them).

Validity, computed at read time (nothing stored):
- round out of date (3B): plan.route_version != round.route_version; the admin must re-optimize;
- awaiting recalculation (4B): the effective route's rider_route_version != the rider's
  `round_riders.route_version`, e.g. after the rider changed their own destination. Only that
  rider is affected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .models import PlanOrder, PlanRoute, RevisionOrder, RoundRider, RouteRevision, RoutePlan


@dataclass
class EffectiveRoute:
    plan: RoutePlan
    plan_route: PlanRoute
    revision: RouteRevision | None
    sequence: dict[uuid.UUID, int]  # order id -> stop number (active Pending orders only)

    @property
    def rider_route_version(self) -> int:
        return self.revision.rider_route_version if self.revision else self.plan_route.rider_route_version

    @property
    def revision_number(self) -> int:
        return self.revision.revision if self.revision else 0

    @property
    def vehicle(self) -> str:
        return (self.revision or self.plan_route).vehicle

    @property
    def endpoint_kind(self) -> str:
        return (self.revision or self.plan_route).endpoint_kind

    @property
    def open_route(self) -> bool:
        return (self.revision or self.plan_route).open_route

    @property
    def road_distance_m(self) -> int:
        return (self.revision or self.plan_route).road_distance_m

    @property
    def road_duration_s(self) -> int:
        return (self.revision or self.plan_route).road_duration_s


def current_revision(db: DBSession, plan_id: uuid.UUID, rider_id: uuid.UUID, *, lock: bool = False) -> RouteRevision | None:
    q = select(RouteRevision).where(RouteRevision.plan_id == plan_id, RouteRevision.rider_id == rider_id,
                                    RouteRevision.is_current.is_(True))
    if lock:
        q = q.with_for_update()
    return db.scalar(q.execution_options(populate_existing=True))


def effective_route(db: DBSession, plan: RoutePlan, rider_id: uuid.UUID) -> EffectiveRoute | None:
    """The rider's effective route in `plan` (None if the plan has no route for them)."""
    plan_route = db.get(PlanRoute, (plan.id, rider_id), populate_existing=True)
    if plan_route is None:
        return None
    revision = current_revision(db, plan.id, rider_id)
    if revision is not None:
        seq = dict(db.execute(select(RevisionOrder.order_id, RevisionOrder.stop_seq)
                              .where(RevisionOrder.revision_id == revision.id)).all())
    else:
        seq = dict(db.execute(select(PlanOrder.order_id, PlanOrder.stop_seq)
                              .where(PlanOrder.plan_id == plan.id, PlanOrder.rider_id == rider_id,
                                     PlanOrder.role == "active")).all())
    return EffectiveRoute(plan, plan_route, revision, seq)


def effective_routes(db: DBSession, plan: RoutePlan) -> dict[uuid.UUID, EffectiveRoute]:
    """Every rider's effective route in `plan` (admin view)."""
    rider_ids = db.scalars(select(PlanRoute.rider_id).where(PlanRoute.plan_id == plan.id)).all()
    return {rid: effective_route(db, plan, rid) for rid in rider_ids}


def awaiting_recalculation(eff: EffectiveRoute, rr: RoundRider | None) -> str | None:
    """Why this rider's own route needs recalculating, or None. Only a rider-scoped change (their
    own destination, R23) moves `round_riders.route_version`; anything round-wide is reported as
    the plan being out of date instead."""
    if rr is not None and eff.rider_route_version != rr.route_version:
        return "destination_changed"
    return None


def revision_view(rev: RouteRevision | None, order_codes: dict) -> dict | None:
    """A revision as shown to its rider or an admin: kinds and order codes, never positions."""
    if rev is None:
        return None
    return {"number": rev.revision, "trigger": rev.trigger, "origin_kind": rev.origin_kind,
            "origin_order_code": order_codes.get(rev.origin_order_id) if rev.origin_order_id else None,
            "created_at": rev.created_at.isoformat()}


ORIGIN_LABELS = {
    "current_position": "your current position (device location)",
    "last_completed_stop": "your last completed stop, not your current position",
    "configured_start": "your configured start, not your current position",
}
