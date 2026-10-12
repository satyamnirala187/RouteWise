"""List candidate coordinates for public landmarks from the local OSM extract.

Usage: python find_landmarks.py <extract.osm.pbf>

Coordinates come from OpenStreetMap itself (© OpenStreetMap contributors, ODbL),
so fixtures are reproducible and need no geocoding service. A way's coordinate
is the mean of its nodes (a representative point, not necessarily a gate).
"""

from __future__ import annotations

import json
import re
import sys

import osmium

TARGETS = {
    "office": r"^Vishwavidyalaya$",
    "warehouse": r"^Azadpur$",
    "home_r1": r"^Model Town$",
    "custom_r2": r"Kashmere Gate|Kashmiri Gate|Maharana Pratap",
    "gps_r1": r"^Faculty of Arts",
    "kirori_mal": r"Kirori Mal",
    "hansraj": r"^Hansraj College",
    "hindu_college": r"^Hindu College",
    "st_stephens": r"St\.? Stephen",
    "miranda_house": r"^Miranda House",
    "ramjas": r"^Ramjas College",
    "srcc": r"Shri Ram College of Commerce",
    "daulat_ram": r"^Daulat Ram College",
    "kamla_nagar": r"^Kamla Nagar",
    "gtb_nagar": r"^(GTB Nagar|Guru Tegh Bahadur Nagar)$",
    "civil_lines": r"^Civil Lines$",
}
KEEP_KEYS = ("railway", "public_transport", "amenity", "place", "shop", "landuse", "building", "highway", "station")


def main() -> int:
    patterns = {k: re.compile(v, re.I) for k, v in TARGETS.items()}
    found: dict[str, list] = {k: [] for k in TARGETS}
    for obj in osmium.FileProcessor(sys.argv[1]).with_locations():
        name = obj.tags.get("name")
        if not name:
            continue
        for key, pat in patterns.items():
            if not pat.search(name):
                continue
            if obj.is_node():
                lat, lon = obj.location.lat, obj.location.lon
            elif obj.is_way():
                pts = [(n.location.lat, n.location.lon) for n in obj.nodes if n.location.valid()]
                if not pts:
                    continue
                lat, lon = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            else:
                continue
            tags = {k: obj.tags.get(k) for k in KEEP_KEYS if obj.tags.get(k)}
            found[key].append({"osm": f"{'n' if obj.is_node() else 'w'}{obj.id}", "name": name,
                               "lat": round(lat, 6), "lng": round(lon, 6), "tags": tags})
    print(json.dumps(found, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
