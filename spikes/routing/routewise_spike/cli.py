"""Phase 0 spike commands.

  python -m routewise_spike capture-osrm      # live OSRM call, writes recorded fixture + evidence (historical)
  python -m routewise_spike capture-valhalla  # local Valhalla (no network): DU recordings + evidence
  python -m routewise_spike google-check      # live Google Routes check (BLOCKED without key)
  python -m routewise_spike run-scenario      # full scenario on the recorded real matrix
  python -m routewise_spike cost-projection   # element volumes and prices for 20/50/100 orders
  python -m routewise_spike stadia-check      # live Stadia matrix check (BLOCKED without key)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .costs import ROUNDS_PER_MONTH, SKUS, projection_table
from .matrix.base import ElementStatus, ProviderError, RoadMatrix
from .models import DistributionMode, Endpoint, EndpointKind, OrderStatus, Plan
from .planner import PlanningError, PlanStore, optimize_round
from .reroute import choose_origin, reroute_rider
from .scenario import RECORDED_OSRM, REPO_ROOT, load_locations, phase0_round

EVIDENCE = REPO_ROOT / "spikes" / "routing" / "evidence"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def asymmetry_pairs(matrix: RoadMatrix, ids: list[str], top: int = 5) -> list[dict]:
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            ab, ba = matrix.get(a, b), matrix.get(b, a)
            if ab.status is ElementStatus.OK and ba.status is ElementStatus.OK:
                pairs.append({"a": a, "b": b, "a_to_b_m": ab.distance_m, "b_to_a_m": ba.distance_m,
                              "diff_m": abs(ab.distance_m - ba.distance_m)})
    return sorted(pairs, key=lambda p: -p["diff_m"])[:top]


def cmd_capture_osrm(args) -> int:
    from .matrix.osrm import DEMO_BASE_URL, OSRMTableProvider

    locs = list(load_locations().values())
    base = os.environ.get("OSRM_BASE_URL") or DEMO_BASE_URL
    provider = OSRMTableProvider(base)
    t0 = time.monotonic()
    try:
        matrix = provider.compute(locs, locs, "car_proxy")
    except ProviderError as exc:
        print(f"OSRM capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    latency_ms = round((time.monotonic() - t0) * 1000)
    raw = provider.last_raw
    for key in ("sources", "destinations"):
        for w in raw.get(key, []):
            w.pop("hint", None)  # opaque server-side hints; not needed for replay
    ids = [loc.id for loc in locs]
    meta = {
        "provider": "OSRM Table service, public demo server",
        "base_url": base,
        "profile": "driving (car) — proxy, NOT a motorized two-wheeler profile",
        "requested_at": matrix.provenance.requested_at,
        "units": {"distance": "meters", "duration": "seconds"},
        "element_count": matrix.provenance.element_count,
        "response_status": matrix.provenance.response_status,
        "latency_ms": latency_ms,
        "attribution": "Road data © OpenStreetMap contributors, ODbL. Routing by OSRM.",
        "usage_note": "Demo server: reasonable non-commercial use, <=1 request/second, no SLA. Research evidence only.",
    }
    RECORDED_OSRM.parent.mkdir(parents=True, exist_ok=True)
    RECORDED_OSRM.write_text(json.dumps(
        {"meta": meta, "locations": [loc.__dict__ for loc in locs], "response": raw}, indent=1))
    snaps = {ids[i]: round(w["distance"], 1) for i, w in enumerate(raw.get("sources", []))}
    no_route = sum(1 for e in matrix.elements.values() if e.status is not ElementStatus.OK)
    summary = meta | {
        "no_route_elements": no_route,
        "snap_distance_m": snaps,
        "largest_directed_asymmetries": asymmetry_pairs(matrix, ids),
        "recorded_fixture": str(RECORDED_OSRM.relative_to(REPO_ROOT)),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "osrm_live_capture.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_google_check(args) -> int:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "google_routes_check.json"
    if not key:
        result = {"checked_at": _now(), "status": "BLOCKED",
                  "reason": "GOOGLE_MAPS_API_KEY not set; no credentials and no approved spending cap (D04/D10)."}
        out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        return 3
    if not args.allow_billing:
        print("Refusing to call a billed API without --allow-billing (TWO_WHEELER bills at the Enterprise SKU).",
              file=sys.stderr)
        return 4
    from .matrix.google_routes import GoogleRoutesMatrixProvider

    locs = list(load_locations().values())[: args.points]
    t0 = time.monotonic()
    try:
        matrix = GoogleRoutesMatrixProvider(key).compute(locs, locs, "two_wheeler")
    except ProviderError as exc:
        result = {"checked_at": _now(), "status": "FAILED", "error": type(exc).__name__, "message": str(exc)}
    else:
        ids = [loc.id for loc in locs]
        # Store metadata only; Google restricts caching of Routes content.
        result = {"checked_at": _now(), "status": "OK", "latency_ms": round((time.monotonic() - t0) * 1000)}
        result |= matrix.provenance.as_dict()
        result["no_route_elements"] = sum(1 for e in matrix.elements.values() if e.status is not ElementStatus.OK)
        result["directed_asymmetry_observed"] = bool(asymmetry_pairs(matrix, ids, 1)
                                                     and asymmetry_pairs(matrix, ids, 1)[0]["diff_m"] > 0)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "OK" else 2


def cmd_stadia_check(args) -> int:
    """Live Stadia matrix check on public test points. Stores metadata only (Stadia ToS §8)."""
    key = os.environ.get("STADIA_API_KEY", "")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "stadia_matrix_check.json"
    if not key:
        result = {"checked_at": _now(), "status": "BLOCKED",
                  "reason": "STADIA_API_KEY not set; no account (matrix needs Standard+ or the 14-day trial)."}
        out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        return 3
    if not args.allow_network:
        print("Refusing to call Stadia without --allow-network (owner approval required).", file=sys.stderr)
        return 4
    from .matrix.stadia import StadiaMatrixProvider

    locs = list(load_locations().values())[: args.points]
    ids = [loc.id for loc in locs]
    provider = StadiaMatrixProvider(key)
    t0 = time.monotonic()
    try:
        matrix = provider.compute(locs, locs, args.costing)
    except ProviderError as exc:
        result = {"checked_at": _now(), "status": "FAILED", "error": type(exc).__name__, "message": str(exc)}
    else:
        asym = asymmetry_pairs(matrix, ids, 1)
        result = {"checked_at": _now(), "status": "OK", "latency_ms": round((time.monotonic() - t0) * 1000),
                  "batches": provider.requests_made} | matrix.provenance.as_dict()
        result["no_route_elements"] = sum(1 for e in matrix.elements.values() if e.status is not ElementStatus.OK)
        result["directed_asymmetry_observed"] = bool(asym and asym[0]["diff_m"] > 0)
        result["test_area"] = "Bengaluru public landmarks (test area only, not the confirmed delivery area)"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "OK" else 2


def _route_lines(plan: Plan, rnd) -> list[str]:
    lines = []
    for rid, r in plan.routes.items():
        stops = " → ".join(
            f"{s.location_id}[{'+'.join(s.order_ids)}]" for s in r.stops
        ) or "(no stops)"
        end = r.end_location_id or "OPEN (Last stop; no return leg)"
        lines.append(
            f"- **{rid}** v{r.version} start `{r.start_location_id}` ({r.origin_kind}) → {stops} → end `{end}` · "
            f"{len(r.order_ids())} active orders · road {r.road_distance_m/1000:.2f} km / {r.road_duration_s/60:.0f} min"
            + (f" · postponed {r.postponed_order_ids}" if r.postponed_order_ids else "")
            + (f" · completed {r.completed_order_ids}" if r.completed_order_ids else "")
        )
    return lines


VALHALLA_DATA = REPO_ROOT / "spikes" / "valhalla" / "data"
DU_BBOX = {"south": 28.55, "west": 77.06, "north": 28.83, "east": 77.36}
DU_DATA_NOTE = ("Geofabrik india-latest.osm.pbf (OSM data up to 2026-10-11T20:21:06Z, md5 95615ee3bb02b3748905024da46137b7) "
                "cut to a buffered box around DU North Campus (S28.55 W77.06 N28.83 E77.36).")


def cmd_capture_valhalla(args) -> int:
    """Run local Valhalla (no network) on the DU public points; record both two-wheeler costings."""
    from .matrix.valhalla_local import ValhallaLocalProvider, to_recording
    from .scenario import DU_LOCATIONS_FILE, RECORDED_VALHALLA

    tiles = VALHALLA_DATA / "valhalla_tiles"
    locs = list(load_locations(DU_LOCATIONS_FILE).values())
    ids = [loc.id for loc in locs]
    provider = ValhallaLocalProvider(tiles, data_note=DU_DATA_NOTE)
    summary: dict = {"captured_at": _now(), "test_area": "DU North Campus, Delhi (confirmed delivery area)",
                     "bbox": DU_BBOX, "data": DU_DATA_NOTE, "points": len(locs), "costings": {}}
    matrices = {}
    for costing in ("motor_scooter", "motorcycle"):
        try:
            m = provider.compute(locs, locs, costing)
        except ProviderError as exc:
            print(f"Valhalla {costing} failed: {exc}", file=sys.stderr)
            return 2
        matrices[costing] = m
        meta = {"test_area": "DU North Campus, Delhi — public landmarks; roles are synthetic",
                "bbox": DU_BBOX, "latency_ms": provider.last_latency_ms}
        RECORDED_VALHALLA[costing].write_text(json.dumps(to_recording(m, locs, meta), indent=1))
        ok = [(a, b) for a in ids for b in ids if a != b and m.get(a, b).status is ElementStatus.OK]
        summary["costings"][costing] = {
            "latency_ms": provider.last_latency_ms,
            "elements": m.provenance.element_count,
            "no_route_pairs": [(a, b) for a in ids for b in ids if a != b and m.get(a, b).status is not ElementStatus.OK],
            "largest_directed_asymmetries": asymmetry_pairs(m, ids, 5),
            "routable_pairs": len(ok),
        }
    s, c = matrices["motor_scooter"], matrices["motorcycle"]
    both = [(a, b) for a in ids for b in ids if a != b and s.get(a, b).status is ElementStatus.OK
            and c.get(a, b).status is ElementStatus.OK]
    diffs = sorted(both, key=lambda p: -abs(s.get(*p).distance_m - c.get(*p).distance_m))[:5]
    summary["profile_comparison"] = {
        "pairs_with_different_distance": sum(1 for p in both if s.get(*p).distance_m != c.get(*p).distance_m),
        "pairs_with_different_time": sum(1 for p in both if s.get(*p).duration_s != c.get(*p).duration_s),
        "total_time_s": {"motor_scooter": sum(s.get(*p).duration_s for p in both),
                         "motorcycle": sum(c.get(*p).duration_s for p in both)},
        "largest_distance_differences": [
            {"from": a, "to": b, "motor_scooter_m": s.get(a, b).distance_m, "motorcycle_m": c.get(a, b).distance_m}
            for a, b in diffs],
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "valhalla_du_capture.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def _provider(kind: str):
    if kind in ("du-motor_scooter", "du-motorcycle"):
        from .matrix.recorded import RecordedMatrixProvider
        from .scenario import RECORDED_VALHALLA

        return RecordedMatrixProvider(RECORDED_VALHALLA[kind.split("-", 1)[1]]), "recorded"
    if kind in ("du-fleet", "du-live-fleet"):
        from .matrix.recorded import ByProfile, RecordedMatrixProvider
        from .matrix.valhalla_local import ValhallaLocalProvider
        from .models import Vehicle
        from .scenario import RECORDED_VALHALLA

        if kind == "du-fleet":
            providers = {c: RecordedMatrixProvider(RECORDED_VALHALLA[c]) for c in RECORDED_VALHALLA}
        else:
            live = ValhallaLocalProvider(VALHALLA_DATA / "valhalla_tiles", data_note=DU_DATA_NOTE)
            providers = {c: live for c in RECORDED_VALHALLA}
        return ByProfile(providers), {Vehicle.SCOOTER: "motor_scooter", Vehicle.BIKE: "motorcycle"}
    if kind in ("du-live-motor_scooter", "du-live-motorcycle"):
        from .matrix.valhalla_local import ValhallaLocalProvider

        return ValhallaLocalProvider(VALHALLA_DATA / "valhalla_tiles", data_note=DU_DATA_NOTE), kind.split("-", 2)[2]
    if kind == "recorded":
        from .matrix.recorded import RecordedOSRMProvider

        return RecordedOSRMProvider(RECORDED_OSRM), "car_proxy"
    if kind == "osrm-live":
        from .matrix.osrm import OSRMTableProvider

        return OSRMTableProvider(os.environ.get("OSRM_BASE_URL") or "https://router.project-osrm.org"), "car_proxy"
    from .matrix.synthetic import SyntheticMatrixProvider

    return SyntheticMatrixProvider(asymmetry=0.1), "synthetic"


def cmd_run_scenario(args) -> int:
    provider, profile = _provider(args.matrix)
    area = "du_north" if args.matrix.startswith("du-") else "bengaluru"
    area_label = ("DU North Campus, Delhi (confirmed delivery area)" if area == "du_north"
                  else "Bengaluru (historical test area; evidence only)")
    md = [f"# Phase 0 scenario run", "", f"Run at {_now()} · matrix source `{args.matrix}` · area: {area_label}", ""]
    log: dict = {"run_at": _now(), "matrix": args.matrix, "steps": []}

    def step(title: str, lines: list[str], data: dict):
        md.extend([f"## {title}", "", *lines, ""])
        log["steps"].append({"title": title} | data)

    # 1. Gate: one rider has not confirmed.
    rnd = phase0_round(confirmed=True, area=area)
    rnd.rider("R3").endpoint.confirmed = False
    try:
        optimize_round(rnd, provider, profile=profile)
        step("1. Endpoint gate", ["UNEXPECTED: optimization ran with an unconfirmed endpoint"], {"passed": False})
    except PlanningError as exc:
        step("1. Endpoint gate", [f"Blocked as required: `{exc.code}` {exc.details}"], {"passed": exc.code == "ENDPOINTS_NOT_CONFIRMED"})
    rnd.rider("R3").endpoint.confirmed = True

    # 2. Smart, equal and manual plans with a first-delivery priority.
    plans = {}
    for mode in (DistributionMode.SMART, DistributionMode.EQUAL):
        r = phase0_round(mode=mode, area=area)
        r.order("O08").first_priority = True
        plans[mode] = optimize_round(r, provider, profile=profile)
        p = plans[mode]
        step(f"2. {mode.value.title()} plan (O08 first priority)",
             [f"Label: **{p.distance_label}**", *_route_lines(p, r), *[f"- warning: {w}" for w in p.warnings]],
             {"distance_label": p.distance_label, "assignments": p.assignments,
              "km": {k: v.road_distance_m / 1000 for k, v in p.routes.items()}})
    manual = phase0_round(mode=DistributionMode.MANUAL, area=area)
    for oid, rid in plans[DistributionMode.EQUAL].assignments.items():
        manual.order(oid).locked_rider_id = rid
    # The admin moves O12 to another rider who still has spare capacity.
    owner = plans[DistributionMode.EQUAL].assignments["O12"]
    load = {r.id: sum(1 for o in manual.orders if o.locked_rider_id == r.id) for r in manual.riders}
    target = next(r.id for r in manual.riders if r.id != owner and load[r.id] < r.capacity)
    manual.order("O12").locked_rider_id = target
    try:
        mp = optimize_round(manual, provider, profile=profile)
        step(f"3. Manual plan (admin assignments fixed, O12 moved {owner} -> {target})",
             [f"Label: **{mp.distance_label}**", *_route_lines(mp, manual)],
             {"assignments": mp.assignments})
    except PlanningError as exc:
        step("3. Manual plan", [f"Explicit result: `{exc.code}` {exc.message} {exc.details}"], {"error": exc.code})

    # 4. Rider-only reroute: complete first stop, postpone next, reroute R1 from GPS.
    rnd = phase0_round(area=area)
    store = PlanStore()
    plan = store.commit(rnd, optimize_round(rnd, provider, profile=profile))
    before = {k: v for k, v in plan.routes.items()}
    r1 = plan.routes["R1"]
    lines = ["Initial plan:", *_route_lines(plan, rnd)]
    if len(r1.stops) >= 2:
        for oid in r1.stops[0].order_ids:
            o = rnd.order(oid)
            o.status, o.completed_at = OrderStatus.COMPLETED, "2026-10-12T05:00:00Z"
        rnd.order(r1.stops[1].order_ids[0]).status = OrderStatus.POSTPONED
    origin = choose_origin(rnd, plan, "R1", gps_location_id="gps_r1")
    out = reroute_rider(rnd, plan, "R1", provider, profile=profile, origin=origin)
    plan2 = store.commit(rnd, out.plan)
    unchanged = all(plan2.routes[k] is before[k] for k in before if k != "R1")
    lines += ["", f"After completing {r1.stops[0].order_ids} and postponing one order, R1 rerouted from `{origin.kind}`:",
              *_route_lines(plan2, rnd),
              f"- other riders' route objects unchanged: **{unchanged}**; ownership unchanged: **{plan2.assignments == plan.assignments}**"]
    step("4. Rider-only reroute (R1)", lines, {"other_routes_unchanged": unchanged,
                                               "ownership_unchanged": plan2.assignments == plan.assignments})

    # 5. Endpoint change for R2 only.
    rnd.rider("R2").endpoint = Endpoint(EndpointKind.WAREHOUSE, None, True)
    origin2 = choose_origin(rnd, plan2, "R2", rider_confirmed=None) if any(
        rnd.order(o).status is OrderStatus.COMPLETED for o, r in plan2.assignments.items() if r == "R2") else None
    from .reroute import RerouteOrigin

    origin2 = origin2 or RerouteOrigin("configured_start", rnd.start_location_id(rnd.rider("R2")),
                                       "Rider confirmed configured start (no GPS, no completed stop)")
    out2 = reroute_rider(rnd, plan2, "R2", provider, profile=profile, origin=origin2)
    plan3 = store.commit(rnd, out2.plan)
    unchanged2 = all(plan3.routes[k] is plan2.routes[k] for k in plan2.routes if k != "R2")
    step("5. Endpoint change (R2 Custom → Warehouse)",
         [*_route_lines(plan3, rnd), f"- other riders unchanged: **{unchanged2}**; ownership unchanged: **{plan3.assignments == plan2.assignments}**"],
         {"other_routes_unchanged": unchanged2, "ownership_unchanged": plan3.assignments == plan2.assignments})

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"scenario_run_{args.matrix}.md").write_text("\n".join(md) + "\n")
    (EVIDENCE / f"scenario_run_{args.matrix}.json").write_text(json.dumps(log, indent=2, default=str))
    print("\n".join(md))
    return 0


def cmd_cost_projection(args) -> int:
    text = "\n".join([
        "# Matrix volume and cost projection",
        "",
        f"Generated {_now()}. Assumptions: {ROUNDS_PER_MONTH} rounds/month; 2 reroutes per rider per round; "
        "locations = orders + 2 starts + 1 distinct fixed end per rider (upper bound); elements = origins × destinations; "
        "≤625 elements per request. Prices: Google Maps Platform global list, USD, page updated 2026-10-08; "
        "free monthly caps applied per SKU. Monthly cost uses the no-reuse column. "
        "Stadia: matrix needs the Standard plan or higher ($80/month, 7.5M credits, 10 credits per element, "
        "+$0.02 per 1,000 extra credits; pricing page read 2026-10-12); batches of <=625 elements bill exactly "
        "origins x destinations; basemap tiles and other credit use are not included.",
        "",
        projection_table(),
        "",
        "SKUs: " + "; ".join(f"{name}: {free:,} free elements/month" for name, (free, _) in SKUS.items()),
    ])
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "cost_projection.md").write_text(text + "\n")
    print(text)
    return 0


def cmd_benchmark(args) -> int:
    """Solver runtime at 20/50/100 orders. Uses a SYNTHETIC matrix: timing only, not route quality."""
    import random

    from .matrix.synthetic import SyntheticMatrixProvider
    from .models import Depots, DeliveryRound, Location, Order, Rider, StartKind, Vehicle

    base = load_locations()
    rows = ["| Orders | Riders | Mode | Solve seconds | Solver status | Strategy |", "|---|---|---|---|---|---|"]
    rng = random.Random(42)
    for n, k in [(20, 3), (50, 5), (100, 8)]:
        locs = {i: base[i] for i in ("office", "warehouse", "home_r1", "custom_r2")}
        for i in range(n):
            lid = f"p{i}"
            locs[lid] = Location(lid, "synthetic point", 12.92 + rng.random() * 0.09, 77.55 + rng.random() * 0.1)
        ends = [Endpoint(EndpointKind.HOME, "home_r1", True), Endpoint(EndpointKind.CUSTOM, "custom_r2", True),
                Endpoint(EndpointKind.LAST_STOP, None, True), Endpoint(EndpointKind.OFFICE, None, True)]
        riders = [Rider(f"R{j+1}", Vehicle.SCOOTER, -(-n // k) + 2, [StartKind.OFFICE, StartKind.WAREHOUSE][j % 2],
                        ends[j % 4]) for j in range(k)]
        for mode in (DistributionMode.SMART, DistributionMode.EQUAL):
            orders = [Order(f"O{i}", f"p{i}") for i in range(n)]
            orders[0].first_priority = True
            rnd = DeliveryRound("bench", Depots("office", "warehouse"), riders, orders, locs, mode)
            t0 = time.monotonic()
            plan = optimize_round(rnd, SyntheticMatrixProvider(asymmetry=0.1), profile="synthetic",
                                  time_limit_s=args.time_limit)
            dt = time.monotonic() - t0
            rows.append(f"| {n} | {k} | {mode.value} | {dt:.2f} | {plan.provenance['solver_status']} | "
                        f"{plan.provenance['solver_strategy']} |")
    text = "\n".join([
        "# Solver runtime benchmark", "",
        f"Generated {_now()} on this machine. SYNTHETIC matrix (timing only — not road distances). "
        f"Fixed seed 42; GLS bounded by 1000 solutions; safety time limit {args.time_limit}s per strategy.", "",
        *rows,
    ])
    (EVIDENCE / "solver_benchmark.md").write_text(text + "\n")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="routewise_spike")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capture-osrm").set_defaults(fn=cmd_capture_osrm)
    sub.add_parser("capture-valhalla").set_defaults(fn=cmd_capture_valhalla)
    g = sub.add_parser("google-check")
    g.add_argument("--allow-billing", action="store_true")
    g.add_argument("--points", type=int, default=6)
    g.set_defaults(fn=cmd_google_check)
    s = sub.add_parser("run-scenario")
    s.add_argument("--matrix", default="recorded",
                   choices=["recorded", "osrm-live", "synthetic", "du-motor_scooter", "du-motorcycle",
                            "du-live-motor_scooter", "du-live-motorcycle", "du-fleet", "du-live-fleet"])
    s.set_defaults(fn=cmd_run_scenario)
    sub.add_parser("cost-projection").set_defaults(fn=cmd_cost_projection)
    st = sub.add_parser("stadia-check")
    st.add_argument("--allow-network", action="store_true")
    st.add_argument("--points", type=int, default=6)
    st.add_argument("--costing", choices=["motor_scooter", "motorcycle"], default="motor_scooter")
    st.set_defaults(fn=cmd_stadia_check)
    b = sub.add_parser("benchmark")
    b.add_argument("--time-limit", type=int, default=30)
    b.set_defaults(fn=cmd_benchmark)
    args = ap.parse_args(argv)
    return args.fn(args)
