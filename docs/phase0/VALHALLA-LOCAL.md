# Local Valhalla evaluation: DU North Campus, Delhi (₹0)

**Dates:** 12–13 October 2026 · **State:** evaluated locally and working. **Phase 0 remains incomplete** until the owner reviews the acceptance gates.

> **Accepted by the owner on 13 October 2026 for local development** at `2a34226` ([owner acceptance record](OWNER-ACCEPTANCE-2026-10-13.md)). This is the current accepted baseline: local Valhalla + OpenStreetMap for DU North Campus, Delhi, with D04–D10 approved as recorded there. The text below is the historical record as written before acceptance. Its "in review / not complete" statements describe that time and are kept unchanged. Phase 1 work is reported in [../phase1/PHASE1-REPORT.md](../phase1/PHASE1-REPORT.md).

**Implementation revision:** the commit titled "Add local Valhalla routing evaluation for DU North Campus" (the commit directly after `a6c2875`; see `git log`). The original Bengaluru evidence (`f6c479e`) is separate and historical.

**Owner constraints (12 Oct 2026):** the delivery area is DU North Campus, Delhi; the routing/service budget is **₹0**; no paid subscriptions or billable services. Stadia and Google remain optional and inactive. No public demo server is used. Nothing here was deployed.

**Attribution:** road data © OpenStreetMap contributors, licensed under ODbL 1.0, downloaded from Geofabrik. Routing by Valhalla (MIT licence), via the pyvalhalla 3.9.1 package. Any map or route display must show "© OpenStreetMap contributors".

## 1. Prerequisites on this Mac

| Check | Result |
|---|---|
| Hardware | Apple M2, 8 cores, 16 GB RAM, ~87 GB free disk |
| Docker / Colima / Podman / Homebrew | Not installed, and **not needed** |
| Valhalla | `pyvalhalla==3.9.1` from PyPI: a cp314 macOS arm64 wheel that bundles the C++ tools (`valhalla_build_tiles`, `valhalla_build_admins`, `valhalla_service`) and an in-process `Actor` |
| OSM tooling | `osmium==4.3.1` (pyosmium) from PyPI |
| Isolation | `spikes/routing/.venv-valhalla` (git-ignored), pinned in `requirements-valhalla.lock`. The core `.venv` and its tests do not need Valhalla |
| **Manual installation needed** | **None** |

**Workaround found:** pyvalhalla's `python -m valhalla <tool>` wrapper reports "Can't find executable" on this Mac, even though the binaries ship in the wheel. `build_tiles.sh` therefore calls them directly from `python -m valhalla print_bin_path`.

## 2. Setup steps (reproducible; `spikes/valhalla/`)

```bash
cd spikes/routing
python3.14 -m venv .venv-valhalla
.venv-valhalla/bin/python -m pip install -r requirements-valhalla.lock
../valhalla/build_tiles.sh                                         # download → buffered extract → admins → tiles
.venv-valhalla/bin/python -m routewise_spike capture-valhalla      # both two-wheeler costings; writes recordings + evidence
.venv-valhalla/bin/python -m routewise_spike run-scenario --matrix du-live-fleet
../routing/.venv-valhalla/bin/python ../valhalla/compare_buffer.py # (from spikes/valhalla) buffer evidence
```

`build_tiles.sh` steps:

1. **Download** Geofabrik `india-latest.osm.pbf` and verify its MD5 against Geofabrik's published `.md5`. The full India file is used because the buffered box crosses Geofabrik's Northern/Central zone boundary: its east edge in Uttar Pradesh is in the Central zone. That was checked against the zones' `.poly` files.
2. **Cut a buffered box** around campus with `extract_bbox.py`: S 28.55, W 77.06, N 28.83, E 77.36, about 31 km × 29 km, covering most of north and central Delhi and the Ghaziabad edge.
   - Roads touching the box are kept whole, with their outside nodes, so routes that leave and re-enter stay valid.
   - Turn restrictions and admin boundaries are kept.
3. **Build the admin database**, then apply the **driving-side fix** (section 5).
4. **Build the routing tiles.**

All data lives in `spikes/valhalla/data/`, which is git-ignored (the OSM extracts and tiles are large and reproducible).

## 3. Resource usage (measured with `/usr/bin/time -l`)

| Step | Wall time | Peak memory | Output |
|---|---|---|---|
| Download India extract | 196 s | — | 1.71 GB (data up to 2026-10-11T20:21:06Z) |
| Buffered extract (single-threaded Python) | 608–615 s | 1.6–2.0 GB | 18 MB PBF: 1,763,049 nodes, 354,066 ways, 147 relations |
| Admin DB | 1.7 s | ~680 MB | 7.6 MB SQLite |
| Routing tiles | 3.5–3.7 s | 0.70–0.86 GB | **51 MB** |
| 17 × 17 matrix (in-process `Actor`) | **93 ms** `motor_scooter`, **61 ms** `motorcycle` | — | 289 elements |

The India download can be deleted after extraction; a monthly refresh repeats steps 1–4 (about 14 minutes, mostly the Python extraction). A faster C++ extractor (`osmium-tool`) would remove most of that time, but it needs a separate install that I didn't make.

## 4. Fixtures: public points around DU North Campus

`tests/fixtures/public_locations_du_north.json` has 17 points. Coordinates come from OSM itself, not from a geocoding service, and each records its OSM object id. Named gates and stations are preferred over campus centroids.

- **Synthetic roles:**
  - Office: Vishwavidyalaya Metro
  - Warehouse: Azadpur bus station
  - Home: Model Town Metro
  - Custom: Kashmere Gate Metro
  - Simulated current position: University of Delhi bus stop
- **Orders:** Kirori Mal, Hansraj Gate 1 (two orders, one building), Hindu, St. Stephen's, Miranda House Gate 1, Ramjas Gate 1, SRCC, the Daulat Ram bus stop, Kamla Nagar, GTB Nagar Metro, Civil Lines Metro.
- **One extra point,** the Daulat Ram campus centroid, exists only for the unroutable-pin test.

No real addresses, homes or customers are used. **Bengaluru results are kept unchanged as historical evidence** (`osrm_bengaluru_car.json`, and the scenario files as committed at `f6c479e`).

## 5. Actual results

**Real directed road matrices (both costings):**
- 16 public points: all 240 directed pairs routable. The only 32 failures all involve the centroid (see below).
- Asymmetry, motor_scooter:

  | Route | Distance | Reverse |
  |---|---|---|
  | Azadpur → DU bus stop | 7,015 m | 4,917 m |
  | Model Town → Miranda House | 3,885 m | 2,115 m |

- Asymmetry, motorcycle:

  | Route | Distance | Reverse |
  |---|---|---|
  | Kashmere Gate → GTB Nagar | 5,235 m | 7,500 m |

- Evidence: `spikes/routing/evidence/valhalla_du_capture.json`.

**The two profiles really differ:** 46 pairs differ in distance and 193 in time. `motorcycle` prefers higher-class roads: Kashmere Gate → Daulat Ram is 4,245 m on `motor_scooter` and 5,809 m on `motorcycle`. Total time over all pairs is 69,233 s versus 66,543 s, so motorcycle is about 4% faster overall.

**Every existing check passes on DU data.** The planner checks (endpoint gate, five endpoints, Last stop, equal/smart/manual, locks, mixed capacities, insufficient capacity, priority and its conflicts, same-building grouping, partial completion, rider-only reroute, origin fallback, endpoint change, stale plans) are parametrized over three real matrices: Bengaluru OSRM (historical), DU `motor_scooter` and DU `motorcycle`. Result: **264 passed, 5 skipped** (the skips are opt-in live/blocked tests). The opt-in local-Valhalla live tests gave **2 passed**, with live output identical to the recordings.

**Mixed fleet (new):** each rider is planned on its own vehicle's matrix: scooters on `motor_scooter`, the motorbike on `motorcycle`. Tests confirm each rider's distance equals its own profile's road cost. An edge missing for only one profile is never used by that vehicle.

**Scenario on DU (`run-scenario --matrix du-fleet`, recorded = live):**

- Gate blocks the unconfirmed R3.
- Smart plan (O08 first priority):

  | Rider | Route | Distance |
  |---|---|---|
  | R1 | Office → SRCC (O08 first) → Miranda House → GTB Nagar → Home | 5.13 km |
  | R2 | Azadpur → … → Civil Lines → Kashmere Gate | 11.76 km |
  | R3 | Azadpur → Kamla Nagar → Kirori Mal → Hansraj (O02+O03 in one stop) → Last stop, no return leg | 6.66 km |

- Equal plan: 4/4/4 orders.
- Manual plan: the admin moves O12 from R2 to R1.
- R1 reroutes from current position after completing O08 and postponing O06: 3.17 km. R2 and R3 are untouched.
- R2's endpoint change re-plans only R2.

**Unroutable pin found in real data:** the Daulat Ram College campus centroid snaps 42 m onto an internal campus road with no routable connection for either profile. The planner now reports this before solving as `UNROUTABLE_LOCATION` (order O09, "choose a pin on a public road, e.g. the gate"), instead of a generic infeasible-plan error.

**The buffer matters** (`compare_buffer.py`, strict campus-only clip of S28.675 W77.200 N28.700 E77.220 versus the buffered graph, motor_scooter, 156 campus pairs):
- **10 pairs become unroutable** without the buffer.
- **18 get longer.** For example, DU bus stop → Vishwavidyalaya Metro is 1,055 m buffered and 2,709 m campus-only, because the direct route leaves the tight box.
- Evidence: `valhalla_buffer_comparison.json`.

**Driving-side handling and what was observed:** Geofabrik's India extract clips the national boundary, so in this build Valhalla logged "India … missing way member … degenerate and will be skipped", and the Delhi and Uttar Pradesh admin rows were stored with `drive_on_right = 1`. `build_tiles.sh` sets `drive_on_right = 0` on every admin row; all rows in this extract are in India, which drives on the left. In this build's admin log, India did not appear among the countries for which access overrides failed to attach. That suggests no country access override was lost, but it is an observation from the log, not a check of Valhalla's source. **Observation for the tested pairs only:** comparing the right-hand and left-hand builds over the same 210 directed pairs (DU points excluding Daulat Ram, for each of `motor_scooter` and `motorcycle`), no distance or time changed. This does not show that the driving side never matters in Valhalla: other pairs, turn costs elsewhere and turn-by-turn guidance were not tested. Evidence: `valhalla_driving_side_effect.json`.

## 6. Limitations (honest)

- **OSM completeness and access tags** on campus roads, gates and one-ways decide the results. One centroid is already unroutable. Pins must be gates or road-side points, validated per order (R05). Data quality against real rider routes is **untested**; the pilot will have to check it.
- **`motorcycle` is BETA** upstream; `motor_scooter` defaults to `use_primary` 0.5 (it avoids primary roads somewhat). Which profile matches the riders is an owner decision.
- **Durations are free-flow** OSM speed estimates, with no traffic, no time of day and no elevation data.
- **Driving side:** set by a database edit, needed because of how the extract was cut. Its effect was observed only on the 210 tested pairs (no change). A future build could use a complete boundary source instead.
- **The extraction is slow** (about 10 minutes of single-threaded Python) and peaks at about 2 GB RAM.
- **Only tested on this Mac.** A production host isn't chosen: with ₹0, that means an existing machine or a verified free tier, an owner decision. The spike runs Valhalla in-process; a production API would run `valhalla_service` or keep the in-process `Actor` in the API worker. That decision belongs to Phase 1/2 design.
- **ODbL:** storing and displaying routes internally is fine with attribution. Publicly distributing a derived database would trigger share-alike.
- **Bengaluru results** are historical only and say nothing about Delhi.
