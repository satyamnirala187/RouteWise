# Phase 0 scenario run

Run at 2026-10-12T16:12:22+00:00 · matrix source `recorded`

## 1. Endpoint gate

Blocked as required: `ENDPOINTS_NOT_CONFIRMED` ['R3: unconfirmed']

## 2. Smart plan (O08 first priority)

Label: **Road distances: osrm-table (OpenStreetMap data), profile car (proxy; not a two-wheeler profile), recorded response captured 2026-10-12T15:59:58+00:00**
- **R1** v1 start `office` (configured_start) → cubbon_park[O01] → ub_city[O02+O03] → mg_road_metro[O04] → forum_koramangala[O09] → end `home_r1` · 5 active orders · road 14.63 km / 29 min
- **R2** v1 start `warehouse` (configured_start) → mantri_square[O07] → bangalore_palace[O06] → shivajinagar_bus[O12] → commercial_street[O05] → ulsoor_lake[O10] → end `custom_r2` · 5 active orders · road 14.60 km / 27 min
- **R3** v1 start `warehouse` (configured_start) → jayanagar_4th_block[O08] → bull_temple[O11] → end `OPEN (Last stop; no return leg)` · 2 active orders · road 10.66 km / 15 min

## 2. Equal plan (O08 first priority)

Label: **Road distances: osrm-table (OpenStreetMap data), profile car (proxy; not a two-wheeler profile), recorded response captured 2026-10-12T15:59:58+00:00**
- **R1** v1 start `office` (configured_start) → cubbon_park[O01] → ub_city[O02+O03] → bull_temple[O11] → end `home_r1` · 4 active orders · road 11.86 km / 21 min
- **R2** v1 start `warehouse` (configured_start) → jayanagar_4th_block[O08] → forum_koramangala[O09] → mg_road_metro[O04] → ulsoor_lake[O10] → end `custom_r2` · 4 active orders · road 23.17 km / 37 min
- **R3** v1 start `warehouse` (configured_start) → mantri_square[O07] → bangalore_palace[O06] → shivajinagar_bus[O12] → commercial_street[O05] → end `OPEN (Last stop; no return leg)` · 4 active orders · road 9.55 km / 20 min

## 3. Manual plan (admin assignments fixed, O12 moved by admin)

Label: **Road distances: osrm-table (OpenStreetMap data), profile car (proxy; not a two-wheeler profile), recorded response captured 2026-10-12T15:59:58+00:00**
- **R1** v1 start `office` (configured_start) → cubbon_park[O01] → shivajinagar_bus[O12] → ub_city[O02+O03] → bull_temple[O11] → end `home_r1` · 5 active orders · road 15.27 km / 26 min
- **R2** v1 start `warehouse` (configured_start) → jayanagar_4th_block[O08] → forum_koramangala[O09] → mg_road_metro[O04] → ulsoor_lake[O10] → end `custom_r2` · 4 active orders · road 23.17 km / 37 min
- **R3** v1 start `warehouse` (configured_start) → mantri_square[O07] → bangalore_palace[O06] → commercial_street[O05] → end `OPEN (Last stop; no return leg)` · 3 active orders · road 9.85 km / 19 min

## 4. Rider-only reroute (R1)

Initial plan:
- **R1** v1 start `office` (configured_start) → cubbon_park[O01] → ub_city[O02+O03] → mg_road_metro[O04] → forum_koramangala[O09] → end `home_r1` · 5 active orders · road 14.63 km / 29 min
- **R2** v1 start `warehouse` (configured_start) → mantri_square[O07] → bangalore_palace[O06] → shivajinagar_bus[O12] → commercial_street[O05] → ulsoor_lake[O10] → end `custom_r2` · 5 active orders · road 14.60 km / 27 min
- **R3** v1 start `warehouse` (configured_start) → bull_temple[O11] → jayanagar_4th_block[O08] → end `OPEN (Last stop; no return leg)` · 2 active orders · road 8.41 km / 12 min

After completing ['O01'] and postponing one order, R1 rerouted from `current_position`:
- **R1** v2 start `gps_r1` (current_position) → ub_city[O03] → mg_road_metro[O04] → forum_koramangala[O09] → end `home_r1` · 3 active orders · road 13.34 km / 24 min · postponed ['O02'] · completed ['O01']
- **R2** v1 start `warehouse` (configured_start) → mantri_square[O07] → bangalore_palace[O06] → shivajinagar_bus[O12] → commercial_street[O05] → ulsoor_lake[O10] → end `custom_r2` · 5 active orders · road 14.60 km / 27 min
- **R3** v1 start `warehouse` (configured_start) → bull_temple[O11] → jayanagar_4th_block[O08] → end `OPEN (Last stop; no return leg)` · 2 active orders · road 8.41 km / 12 min
- other riders' route objects unchanged: **True**; ownership unchanged: **True**

## 5. Endpoint change (R2 Custom → Warehouse)

- **R1** v2 start `gps_r1` (current_position) → ub_city[O03] → mg_road_metro[O04] → forum_koramangala[O09] → end `home_r1` · 3 active orders · road 13.34 km / 24 min · postponed ['O02'] · completed ['O01']
- **R2** v2 start `warehouse` (configured_start) → mantri_square[O07] → bangalore_palace[O06] → ulsoor_lake[O10] → commercial_street[O05] → shivajinagar_bus[O12] → end `warehouse` · 5 active orders · road 17.66 km / 31 min
- **R3** v1 start `warehouse` (configured_start) → bull_temple[O11] → jayanagar_4th_block[O08] → end `OPEN (Last stop; no return leg)` · 2 active orders · road 8.41 km / 12 min
- other riders unchanged: **True**; ownership unchanged: **True**

