#!/usr/bin/env bash
# Build local Valhalla routing tiles for the buffered DU North Campus test area.
# Requires spikes/routing/.venv-valhalla (pyvalhalla 3.9.1 + osmium 4.3.1).
# Everything is written under spikes/valhalla/data/ (git-ignored). No paid service.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/../routing/.venv-valhalla/bin/python"
DATA="$HERE/data"
# Buffered box around DU North Campus (~31 km x 29 km): south west north east
BBOX="28.55 77.06 28.83 77.36"
mkdir -p "$DATA"
cd "$DATA"

if [ ! -f india-latest.osm.pbf ]; then
  curl -sS -L --retry 3 -o india-latest.osm.pbf https://download.geofabrik.de/asia/india-latest.osm.pbf
  curl -sS -o india-latest.osm.pbf.md5 https://download.geofabrik.de/asia/india-latest.osm.pbf.md5
fi
md5 -q india-latest.osm.pbf | grep -q "$(cut -d' ' -f1 india-latest.osm.pbf.md5)" || { echo "checksum mismatch"; exit 1; }

if [ ! -s du-north-buffer.osm.pbf ]; then
  /usr/bin/time -l "$PY" "$HERE/extract_bbox.py" india-latest.osm.pbf du-north-buffer.osm.pbf $BBOX 2> extract_time.log
fi
# pyvalhalla 3.9.1's `python -m valhalla <tool>` wrapper reports "Can't find executable"
# on this Mac although the binaries ship in the wheel, so call them directly.
BIN="$("$PY" -m valhalla print_bin_path | tail -1)"
"$PY" -m valhalla.valhalla_build_config \
  --mjolnir-tile-dir "$DATA/valhalla_tiles" \
  --mjolnir-tile-extract "$DATA/valhalla_tiles.tar" \
  --mjolnir-admin "$DATA/admins.sqlite" \
  --mjolnir-timezone "$DATA/timezones.sqlite" > valhalla.json
/usr/bin/time -l "$BIN/valhalla_build_admins" -c valhalla.json du-north-buffer.osm.pbf > build_admins.log 2> build_admins_time.log
# Geofabrik's India extract clips the national boundary, so Valhalla drops the India
# country polygon as degenerate ("missing way member ... will be skipped") and the state
# polygons (Delhi, Uttar Pradesh) fall back to right-hand traffic. Every admin area in
# this India-only extract is in India, which drives on the LEFT. (In our build log India
# was not among countries whose access overrides failed to attach; observed, not verified.)
sqlite3 admins.sqlite "UPDATE admins SET drive_on_right = 0;"
[ "$(sqlite3 admins.sqlite 'SELECT COUNT(*) FROM admins WHERE drive_on_right != 0;')" = "0" ] || { echo "driving-side fix failed"; exit 1; }
/usr/bin/time -l "$BIN/valhalla_build_tiles" -c valhalla.json du-north-buffer.osm.pbf > build_tiles.log 2> build_tiles_time.log
echo "tiles: $(du -sh valhalla_tiles | cut -f1); extract: $(du -h du-north-buffer.osm.pbf | cut -f1)"
