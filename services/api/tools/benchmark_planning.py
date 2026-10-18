"""Local planning benchmark on real local Valhalla tiles (DU North Campus), for choosing the
application's planning limits. No database, no network, no paid service.

Usage: .venv/bin/python tools/benchmark_planning.py [output-dir]

Orders are SYNTHETIC benchmark points: a regular grid over the DU North Campus area, kept only
where the local road graph connects the point in both directions (so a size measures solving,
not unroutable pins). Office/Warehouse/Home/Custom are the synthetic roles on public stations
from tests/fixtures/public_locations_du_north.json. Nothing here is a real address.
"""

from __future__ import annotations

import json
import math
import platform
import resource
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from routewise_api.config import REPO_ROOT, PlanningLimits, load_settings  # noqa: E402
from routewise_api.planning import OrderSnap, RiderSnap, Snapshot, prepare, solve  # noqa: E402
from routewise_api.routing import planner  # noqa: E402
from routewise_api.routing.domain import Location  # noqa: E402
from routewise_api.routing.matrix.valhalla_local import ValhallaLocalProvider  # noqa: E402

FIXTURE = {p["id"]: p for p in json.loads((REPO_ROOT / "tests/fixtures/public_locations_du_north.json").read_text())["locations"]}
SIZES = [(20, 3), (40, 4), (60, 6), (80, 6), (100, 8), (120, 8)]
SOLVE_SECONDS = 30  # the accepted spike's per-strategy safety limit, to see natural solve times


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # bytes on macOS


def grid_points(n: int) -> list[Location]:
    side = math.ceil(math.sqrt(n))
    pts = []
    for i in range(side):
        for j in range(side):
            pts.append(Location(f"G{len(pts)}", "synthetic benchmark point",
                                round(28.676 + 0.028 * i / (side - 1), 6), round(77.196 + 0.030 * j / (side - 1), 6)))
    return pts


def routable(provider, candidates: list[Location]) -> list[Location]:
    """Drop the worst-connected point until every directed pair has a road route in both profiles."""
    for profile in ("motor_scooter", "motorcycle"):
        while True:
            m = provider.compute(candidates, candidates, profile)
            fails: dict[str, int] = {}
            for (a, b), e in m.elements.items():
                if e.status.value != "ok":
                    fails[a] = fails.get(a, 0) + 1
                    fails[b] = fails.get(b, 0) + 1
            if not fails:
                break
            worst = max(fails, key=lambda k: (fails[k], k))
            candidates = [c for c in candidates if c.id != worst]
    return candidates


def snapshot(points: list[Location], riders: int) -> Snapshot:
    kinds = ["home", "custom", "last_stop", "office", "warehouse"]
    rider_snaps = []
    cap = math.ceil(len(points) / riders) + 2
    for i in range(riders):
        kind = kinds[i % len(kinds)]
        dest = {"home": FIXTURE["home_r1"], "custom": FIXTURE["custom_r2"]}.get(kind)
        rider_snaps.append(RiderSnap(uuid.UUID(int=i + 1), f"Bench rider {i + 1}", True,
                                     "scooter" if i % 2 == 0 else "bike", cap, "office" if i % 2 == 0 else "warehouse",
                                     1, True, kind, dest["lat"] if dest else None, dest["lng"] if dest else None))
    orders = tuple(OrderSnap(uuid.UUID(int=10_000 + k), f"BENCH-{k:04d}", "Pending", "resolved", p.lat, p.lng,
                             None, False, None) for k, p in enumerate(points))
    depots = tuple((k, FIXTURE[k]["lat"], FIXTURE[k]["lng"]) for k in ("office", "warehouse"))
    return Snapshot(uuid.UUID(int=0), 1, "smart", depots, tuple(rider_snaps), orders)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "docs/phase2/evidence"
    settings = load_settings()
    huge = PlanningLimits(max_pending_orders=10_000, max_riders=100, max_locations=400, solve_seconds=SOLVE_SECONDS)
    settings = replace(settings, planning=huge)
    t0 = time.monotonic()
    provider = ValhallaLocalProvider(settings.valhalla_tiles, max_locations=400)
    init_s = time.monotonic() - t0
    pool = routable(provider, grid_points(196))
    results = []
    for n_orders, n_riders in SIZES:
        if n_orders > len(pool):
            break
        for mode in ("smart", "equal"):
            snap = replace(snapshot(pool[:n_orders], n_riders), mode=mode)
            prepared = prepare(snap, settings)
            row = {"orders": n_orders, "riders": n_riders, "mode": mode, "points": prepared.locations,
                   "matrix_cells_per_profile": prepared.locations ** 2}
            try:
                solved = solve(prepared, provider, settings.planning)
                row |= solved.timings | {"solver_status": solved.plan.provenance["solver_status"],
                                         "solver_strategy": solved.plan.provenance["solver_strategy"],
                                         "objective_m": solved.plan.provenance["objective"], "ok": True}
            except planner.PlanningError as exc:
                row |= {"ok": False, "error": exc.code}
            row["max_rss_mb"] = round(rss_mb())
            results.append(row)
            print(json.dumps(row), flush=True)
    snaps = {}
    for profile in ("motor_scooter", "motorcycle"):
        fixture_pts = [Location(k, "", v["lat"], v["lng"]) for k, v in FIXTURE.items()]
        snaps[profile] = {"public_fixture_points_m": provider.snap_distances_m(fixture_pts, profile)}
        grid = provider.snap_distances_m(pool, profile)
        vals = sorted(v for v in grid.values() if v is not None)
        snaps[profile]["synthetic_points_m"] = {"count": len(vals), "median": vals[len(vals) // 2], "max": vals[-1]}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": f"{platform.machine()} {platform.platform()}", "python": platform.python_version(),
        "provider": "valhalla-local (in-process pyvalhalla 3.9.1, OSM tiles built by spikes/valhalla/build_tiles.sh)",
        "actor_init_s": round(init_s, 2), "solve_seconds_per_strategy": SOLVE_SECONDS,
        "synthetic_points_kept": len(pool), "synthetic_points_tried": 196,
        "note": "Synthetic grid orders, not addresses. Durations are traffic-free. Solve times vary by machine.",
        "results": results, "snap_distances": snaps,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "local_routing_benchmark.json").write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
