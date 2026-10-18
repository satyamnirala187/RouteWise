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
