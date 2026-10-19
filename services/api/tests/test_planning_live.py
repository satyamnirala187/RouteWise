"""Opt-in: a full API planning run on the real local Valhalla tiles (no recording, no network).

    ROUTEWISE_LIVE_TESTS=1 .venv/bin/python -m pytest -q -m live tests/test_planning_live.py

Needs spikes/valhalla/data/valhalla_tiles (built by spikes/valhalla/build_tiles.sh). Customers
are synthetic; locations are public OSM points around DU North Campus."""

import json
import math
import os

import pytest

from .planning_world import PUBLIC_DU, make_world, optimize, recorded_cost, route_points, wait_run

pytestmark = pytest.mark.live


def bline_m(a, b) -> float:
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b["lng"] - a["lng"]) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


@pytest.mark.skipif(os.environ.get("ROUTEWISE_LIVE_TESTS") != "1", reason="set ROUTEWISE_LIVE_TESTS=1 (local tiles)")
def test_live_local_valhalla_plan(app, admin, db):
    if not app.state.settings.valhalla_tiles.is_dir():
        pytest.skip("local Valhalla tiles not built")
    w = make_world(app, admin, db, live=True)
    run = wait_run(w, optimize(w).json()["id"], timeout=180)
    assert run["state"] == "succeeded", run
    plan = w.admin.get(f"/api/admin/rounds/{w.rid}/plan").json()
    prov = plan["provenance"]
    assert prov["real_road"] is True and prov["recorded"] is False
    assert prov["provider"].startswith("valhalla-local") and "OpenStreetMap" in prov["notes"]
    assert {r["profile"] for r in plan["routes"]} == {"motor_scooter", "motorcycle"}
    for r in plan["routes"]:
        path = route_points(w, r)
        # Live tiles are the ones the Phase 0 recording came from: identical directed costs.
        assert (r["road_distance_m"], r["road_duration_s"]) == recorded_cost(r["profile"], path)
        for a, b in zip(path, path[1:]):  # never shorter than the straight line (snapping tolerance)
            assert recorded_cost(r["profile"], [a, b])[0] >= 0.8 * bline_m(PUBLIC_DU[a], PUBLIC_DU[b]) - 300
    print("\nLIVE", json.dumps({"timings": run["timings"], "provider": prov["provider"],
                                "response_status": prov["response_status"], "profile": prov["profile"],
                                "requested_at": prov["requested_at"], "solver_status": prov["solver_status"],
                                "total_road_distance_m": plan["summary"]["total_road_distance_m"]}))


@pytest.mark.skipif(os.environ.get("ROUTEWISE_LIVE_TESTS") != "1", reason="set ROUTEWISE_LIVE_TESTS=1 (local tiles)")
def test_live_local_valhalla_rider_reroute(app, admin, db):
    """4B on the real local tiles: a rider reroutes their own remainder from a (synthetic) device
    position; the revision is real road, not recorded, and matches the directed recorded costs."""
    from .test_reroute import gps, planned, reroute_now
    from .test_rider_deliveries import deliveries, seq_codes
    from .test_rider_status import update

    if not app.state.settings.valhalla_tiles.is_dir():
        pytest.skip("local Valhalla tiles not built")
    w = make_world(app, admin, db, live=True)
    planned(w)
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    update(w, "Rider A", seq_codes(view)[0], "Completed")
    run = reroute_now(w, "Rider A", gps())
    view = deliveries(w.browsers["Rider A"], w.rid).json()
    rr = view["plan"]["rider_route"]
    from routewise_api.models import PlanningRun, RouteRevision
    db.expire_all()
    rev = db.query(RouteRevision).one()
    timings = db.get(PlanningRun, rev.run_id).timings
    assert rev.provenance["real_road"] is True and rev.provenance["recorded"] is False
    assert rev.provenance["provider"].startswith("valhalla-local") and rev.profile == "motor_scooter"
    path = ["gps_r1"] + [w.codes[c] for c in seq_codes(view)] + ["home_r1"]
    assert (rr["road_distance_m"], rr["road_duration_s"]) == recorded_cost("motor_scooter", path)
    print("\nLIVE-REROUTE", json.dumps({"state": run["state"], "origin_kind": run["origin_kind"],
                                        "stops": len(seq_codes(view)), "road_distance_m": rr["road_distance_m"],
                                        "provider": rev.provenance["provider"], "solver_status": rev.provenance["solver_status"],
                                        "timings": timings}))
