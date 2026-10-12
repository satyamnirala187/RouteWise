"""Mutation check: inject known defects into a scratch copy and confirm the tests fail.

Usage: python tools/mutation_check.py <scratch copy of repo root> <python with spike deps>
Never run it against the working tree: it rewrites source files in the given copy.
"""
import pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1]); py = sys.argv[2]
P = root / "spikes/routing/routewise_spike"
mutants = {
 "gate disabled": ("planner.py", "    gate = endpoint_gate_issues(rnd)\n", "    gate = []\n"),
 "missing edge -> zero cost": ("planner.py", "                if c is None:\n                    cost[a][b] = FORBIDDEN\n                    allowed[a][b] = False\n", "                if c is None:\n                    cost[a][b] = 0\n"),
 "last-stop sink charged as return": ("planner.py", "    if vehicle.end_location_id is not None:\n        path.append(vehicle.end_location_id)\n", "    path.append(vehicle.end_location_id or vehicle.start_location_id)\n"),
 "manual lock ignored": ("planner.py", "            routing.VehicleVar(idx).SetValues([v_index[s.locked_rider_id]])\n", "            pass\n"),
 "priority ignored": ("planner.py", "                    routing.NextVar(manager.NodeToIndex(j)).RemoveValue(idx)\n", "                    pass\n"),
 "building grouping off": ("planner.py", 'key = ("b", o.building_id, o.location_id, o.locked_rider_id) if o.building_id else ("o", o.id)', 'key = ("o", o.id)'),
 "reroute touches other riders": ("reroute.py", "        routes={**plan.routes, rider_id: route},", "        routes={**{k: __import__('copy').deepcopy(v) for k, v in plan.routes.items()}, rider_id: route},"),
 "postponed kept in sequence": ("reroute.py", "    pending = [o for o in owned if rnd.order(o).status is OrderStatus.PENDING]", "    pending = [o for o in owned if rnd.order(o).status is not OrderStatus.COMPLETED]"),
 "google ROUTE_NOT_FOUND -> 0": ("matrix/google_routes.py", '                out[key] = MatrixElement(ElementStatus.NO_ROUTE)\n', '                out[key] = MatrixElement(ElementStatus.OK, 0, 0)\n'),
 "synthetic labelled real": ("matrix/synthetic.py", "                real_road=False,", "                real_road=True,"),
 "camera centre accepted": ("linkresolve.py", '        return LinkResult("needs_correction", reason="map camera centre only; not a destination pin")', '        m = re.search(r"@(-?[\\d.]+),(-?[\\d.]+)", path); return _coords(m.group(1), m.group(2), "camera")'),
 "private DNS allowed": ("linkresolve.py", "        if not addrs or not all(_is_public(a) for a in addrs):", "        if not addrs:"),
 "capacity precheck off": ("planner.py", "    if len(rnd.orders) > total_cap:", "    if False:"),
}
for name, (f, old, new) in mutants.items():
    p = P / f; orig = p.read_text()
    assert old in orig, name
    p.write_text(orig.replace(old, new, 1))
    r = subprocess.run([py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"], cwd=root / "spikes/routing", capture_output=True, text=True)
    p.write_text(orig)
    print(f"{'KILLED' if r.returncode else 'SURVIVED'}: {name}")
