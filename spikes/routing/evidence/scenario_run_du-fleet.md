# Phase 0 scenario run

Run at 2026-10-12T18:39:17+00:00 · matrix source `du-fleet` · area: DU North Campus, Delhi (confirmed delivery area)

## 1. Endpoint gate

Blocked as required: `ENDPOINTS_NOT_CONFIRMED` ['R3: unconfirmed']

## 2. Smart plan (O08 first priority)

Label: **Road distances: valhalla-local (OpenStreetMap data), profile motor_scooter (scooter), motorcycle (bike), recorded response captured 2026-10-12T18:21:31+00:00**
- **R1** v1 start `office` (configured_start) → srcc[O08] → miranda_house[O06] → gtb_nagar[O11] → end `home_r1` · 3 active orders · road 5.13 km / 9 min
- **R2** v1 start `warehouse` (configured_start) → daulat_ram[O09] → ramjas[O07] → st_stephens[O05] → hindu_college[O04] → civil_lines[O12] → end `custom_r2` · 5 active orders · road 11.76 km / 22 min
- **R3** v1 start `warehouse` (configured_start) → kamla_nagar[O10] → kirori_mal[O01] → hansraj[O02+O03] → end `OPEN (Last stop; no return leg)` · 4 active orders · road 6.66 km / 12 min

## 2. Equal plan (O08 first priority)

Label: **Road distances: valhalla-local (OpenStreetMap data), profile motor_scooter (scooter), motorcycle (bike), recorded response captured 2026-10-12T18:21:31+00:00**
- **R1** v1 start `office` (configured_start) → hindu_college[O04] → daulat_ram[O09] → miranda_house[O06] → gtb_nagar[O11] → end `home_r1` · 4 active orders · road 5.86 km / 10 min
- **R2** v1 start `warehouse` (configured_start) → srcc[O08] → ramjas[O07] → st_stephens[O05] → civil_lines[O12] → end `custom_r2` · 4 active orders · road 11.22 km / 20 min
- **R3** v1 start `warehouse` (configured_start) → kamla_nagar[O10] → kirori_mal[O01] → hansraj[O02+O03] → end `OPEN (Last stop; no return leg)` · 4 active orders · road 6.66 km / 12 min

## 3. Manual plan (admin assignments fixed, O12 moved R2 -> R1)

Label: **Road distances: valhalla-local (OpenStreetMap data), profile motor_scooter (scooter), motorcycle (bike), recorded response captured 2026-10-12T18:21:31+00:00**
- **R1** v1 start `office` (configured_start) → civil_lines[O12] → hindu_college[O04] → daulat_ram[O09] → miranda_house[O06] → gtb_nagar[O11] → end `home_r1` · 5 active orders · road 9.04 km / 17 min
- **R2** v1 start `warehouse` (configured_start) → srcc[O08] → ramjas[O07] → st_stephens[O05] → end `custom_r2` · 3 active orders · road 10.21 km / 17 min
- **R3** v1 start `warehouse` (configured_start) → kamla_nagar[O10] → kirori_mal[O01] → hansraj[O02+O03] → end `OPEN (Last stop; no return leg)` · 4 active orders · road 6.66 km / 12 min

## 4. Rider-only reroute (R1)

Initial plan:
- **R1** v1 start `office` (configured_start) → srcc[O08] → miranda_house[O06] → gtb_nagar[O11] → end `home_r1` · 3 active orders · road 5.13 km / 9 min
- **R2** v1 start `warehouse` (configured_start) → daulat_ram[O09] → ramjas[O07] → st_stephens[O05] → hindu_college[O04] → civil_lines[O12] → end `custom_r2` · 5 active orders · road 11.76 km / 22 min
- **R3** v1 start `warehouse` (configured_start) → kamla_nagar[O10] → kirori_mal[O01] → hansraj[O02+O03] → end `OPEN (Last stop; no return leg)` · 4 active orders · road 6.66 km / 12 min

After completing ['O08'] and postponing one order, R1 rerouted from `current_position`:
- **R1** v2 start `gps_r1` (current_position) → gtb_nagar[O11] → end `home_r1` · 1 active orders · road 3.17 km / 4 min · postponed ['O06'] · completed ['O08']
- **R2** v1 start `warehouse` (configured_start) → daulat_ram[O09] → ramjas[O07] → st_stephens[O05] → hindu_college[O04] → civil_lines[O12] → end `custom_r2` · 5 active orders · road 11.76 km / 22 min
- **R3** v1 start `warehouse` (configured_start) → kamla_nagar[O10] → kirori_mal[O01] → hansraj[O02+O03] → end `OPEN (Last stop; no return leg)` · 4 active orders · road 6.66 km / 12 min
- other riders' route objects unchanged: **True**; ownership unchanged: **True**

## 5. Endpoint change (R2 Custom → Warehouse)

- **R1** v2 start `gps_r1` (current_position) → gtb_nagar[O11] → end `home_r1` · 1 active orders · road 3.17 km / 4 min · postponed ['O06'] · completed ['O08']
- **R2** v2 start `warehouse` (configured_start) → daulat_ram[O09] → ramjas[O07] → st_stephens[O05] → hindu_college[O04] → civil_lines[O12] → end `warehouse` · 5 active orders · road 16.06 km / 27 min
- **R3** v1 start `warehouse` (configured_start) → kamla_nagar[O10] → kirori_mal[O01] → hansraj[O02+O03] → end `OPEN (Last stop; no return leg)` · 4 active orders · road 6.66 km / 12 min
- other riders unchanged: **True**; ownership unchanged: **True**

