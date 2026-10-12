"""Spike-only HTTP boundary proving the endpoint-confirmation gate is enforced
server-side. Not the Phase 1 API: no auth, no persistence, in-memory round.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .matrix.base import MatrixProvider
from .models import DeliveryRound, Endpoint, EndpointKind
from .planner import PlanningError, PlanStore, optimize_round


class EndpointIn(BaseModel):
    kind: EndpointKind
    location_id: str | None = None
    confirm: bool = False


def create_app(rnd: DeliveryRound, provider: MatrixProvider, profile: str) -> FastAPI:
    app = FastAPI(title="RouteWise Phase 0 spike")
    store = PlanStore()

    @app.put("/rounds/{round_id}/riders/{rider_id}/endpoint")
    def set_endpoint(round_id: str, rider_id: str, body: EndpointIn):
        if round_id != rnd.id:
            raise HTTPException(404)
        try:
            rider = rnd.rider(rider_id)
        except KeyError:
            raise HTTPException(404) from None
        rider.endpoint = Endpoint(body.kind, body.location_id, body.confirm)
        return {"rider_id": rider_id, "kind": body.kind, "confirmed": body.confirm}

    @app.post("/rounds/{round_id}/optimize")
    def optimize(round_id: str):
        if round_id != rnd.id:
            raise HTTPException(404)
        try:
            plan = optimize_round(rnd, provider, profile=profile)
        except PlanningError as exc:
            status = 409 if exc.code == "ENDPOINTS_NOT_CONFIRMED" else 422
            raise HTTPException(status, {"code": exc.code, "message": exc.message, "details": exc.details}) from None
        store.commit(rnd, plan)
        return {
            "version": plan.version,
            "distance_label": plan.distance_label,
            "routes": {
                rid: {"orders": r.order_ids(), "road_distance_m": r.road_distance_m}
                for rid, r in plan.routes.items()
            },
        }

    return app
