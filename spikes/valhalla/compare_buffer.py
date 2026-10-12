"""Evidence for the buffered extract: compare a campus-only graph with the buffered graph.

Usage: python compare_buffer.py   (after build_tiles.sh; local only, no network)

Cuts a tight box around DU North Campus out of the buffered extract (strict clip: only
roads entirely inside the box, i.e. a naive campus-only extract), builds a second
tile set with the same admin database, and compares motor_scooter matrices for the
fixture points that lie inside the tight box. Data © OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "spikes" / "routing"))

from routewise_spike.matrix.base import ElementStatus  # noqa: E402
from routewise_spike.matrix.valhalla_local import ValhallaLocalProvider  # noqa: E402
from routewise_spike.scenario import DU_LOCATIONS_FILE, load_locations  # noqa: E402

TIGHT = (28.675, 77.200, 28.700, 77.220)  # south, west, north, east: campus core only


def build_tight() -> Path:
    out = DATA / "campus_only"
    if out.exists():
        import shutil

        shutil.rmtree(out)
    out.mkdir()
    pbf = out / "campus-only.osm.pbf"
    subprocess.run([sys.executable, str(HERE / "extract_bbox.py"), str(DATA / "du-north-buffer.osm.pbf"), str(pbf),
                    *map(str, TIGHT), "--strict"], check=True)
    cfg = json.loads((DATA / "valhalla.json").read_text())
    cfg["mjolnir"]["tile_dir"] = str(out / "valhalla_tiles")
    cfg["mjolnir"]["tile_extract"] = str(out / "valhalla_tiles.tar")
    (out / "valhalla.json").write_text(json.dumps(cfg))
    bin_dir = subprocess.run([sys.executable, "-m", "valhalla", "print_bin_path"], capture_output=True, text=True,
                             check=True).stdout.strip().splitlines()[-1]
    subprocess.run([f"{bin_dir}/valhalla_build_tiles", "-c", str(out / "valhalla.json"), str(pbf)], check=True,
                   capture_output=True)
    return out / "valhalla_tiles"


def main() -> int:
    s, w, n, e = TIGHT
    pts = [p for p in load_locations(DU_LOCATIONS_FILE).values() if s <= p.lat <= n and w <= p.lng <= e]
    ids = [p.id for p in pts]
    buffered = ValhallaLocalProvider(DATA / "valhalla_tiles").compute(pts, pts, "motor_scooter")
    tight = ValhallaLocalProvider(build_tight()).compute(pts, pts, "motor_scooter")
    rows, lost, longer = [], 0, 0
    for a in ids:
        for b in ids:
            if a == b:
                continue
            x, y = buffered.get(a, b), tight.get(a, b)
            if x.status is ElementStatus.OK and y.status is not ElementStatus.OK:
                lost += 1
            elif x.status is ElementStatus.OK and y.status is ElementStatus.OK and y.distance_m > x.distance_m + 50:
                longer += 1
                rows.append({"from": a, "to": b, "buffered_m": x.distance_m, "campus_only_m": y.distance_m})
    result = {
        "tight_box": dict(zip(("south", "west", "north", "east"), TIGHT)),
        "points_inside_tight_box": ids,
        "pairs": len(ids) * (len(ids) - 1),
        "routable_with_buffer_only": lost,
        "longer_without_buffer": longer,
        "largest_increases": sorted(rows, key=lambda r: r["buffered_m"] - r["campus_only_m"])[:8],
        "costing": "motor_scooter",
        "clip": "strict (only roads entirely inside the tight box)",
    }
    out = REPO / "spikes" / "routing" / "evidence" / "valhalla_buffer_comparison.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
