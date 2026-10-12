"""Cut a reference-complete, buffered OSM extract for local Valhalla.

Usage: python extract_bbox.py <input.osm.pbf> <output.osm.pbf> SOUTH WEST NORTH EAST [--strict]

--strict keeps only ways that lie entirely inside the box (a naive clip). It exists
only to demonstrate what a buffer protects against; never use it for routing.

Keeps every node inside the box, every way touching it (completed with its
outside nodes, so roads that leave and re-enter the box stay routable), turn
restrictions touching kept ways, and administrative boundaries (admin_level 2
and 4) touching the box so Valhalla's admin database knows the country (India
drives on the left; country access defaults apply). The India country relation is
always kept with its full border. Data © OpenStreetMap
contributors, ODbL 1.0.
"""

from __future__ import annotations

import sys
import time

import osmium


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    south, west, north, east = map(float, sys.argv[3:7])
    strict = "--strict" in sys.argv[7:]
    t0 = time.monotonic()
    nodes: set[int] = set()
    ways: set[int] = set()
    counts = {"nodes": 0, "ways": 0, "relations": 0}
    with osmium.BackReferenceWriter(dst, ref_src=src, overwrite=True) as writer:
        for obj in osmium.FileProcessor(src):
            if obj.is_node():
                loc = obj.location
                if loc.valid() and south <= loc.lat <= north and west <= loc.lon <= east:
                    nodes.add(obj.id)
                    writer.add_node(obj)
                    counts["nodes"] += 1
            elif obj.is_way():
                keep = all(n.ref in nodes for n in obj.nodes) if strict else any(n.ref in nodes for n in obj.nodes)
                if keep:
                    ways.add(obj.id)
                    writer.add_way(obj)
                    counts["ways"] += 1
            elif obj.is_relation():
                tags = obj.tags
                is_restriction = tags.get("type") in ("restriction", "restriction:motorcar")
                is_admin = tags.get("boundary") == "administrative" and tags.get("admin_level") in ("2", "4")
                # The country relation's border is far from a city box, so a member test would
                # drop it; Valhalla then defaults to right-hand traffic. Always keep India.
                if is_admin and tags.get("admin_level") == "2" and tags.get("ISO3166-1") == "IN":
                    writer.add_relation(obj)
                    counts["relations"] += 1
                elif (is_restriction or is_admin) and any(
                    (m.type == "w" and m.ref in ways) or (m.type == "n" and m.ref in nodes) for m in obj.members
                ):
                    writer.add_relation(obj)
                    counts["relations"] += 1
    print(f"kept {counts} in {time.monotonic() - t0:.0f}s -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
