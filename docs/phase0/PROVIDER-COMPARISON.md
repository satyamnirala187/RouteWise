# Routing-provider comparison (D04) — for review

**State:** proposal for the owner. **Superseded in part by the ₹0 budget** (see the Recommendation). **Corrected earlier on 2026-10-12** after the plan-grid and terms checks in [STADIA-SUITABILITY.md](STADIA-SUITABILITY.md): the Stadia matrix needs the **Standard plan ($80/month)**, not Starter ($20), and storage and benchmarking questions are unresolved. Nothing has been activated, purchased or called for these providers. Facts come from official documentation read on **12 October 2026**; prices and terms change. Google is **not** mandatory. Whichever provider is selected must pass the real road-routing acceptance check (criterion 2) with live evidence for that provider.

## Summary

| | 1. Google Routes (`TWO_WHEELER`) | 2. Stadia Maps — hosted Valhalla on OSM | 3. Self-hosted Valhalla (OSM) |
|---|---|---|---|
| Motorbike / scooter support | `TWO_WHEELER` = motorized two-wheelers. **Beta**; apps must show a beta warning on two-wheel routes | Service limits list motor scooter and motorcycle modes. Valhalla `motor_scooter` (not beta; mopeds; default 45 km/h; avoids higher-class roads unless the country allows them); `motorcycle` (**beta**) | Same Valhalla costings: `motor_scooter`, `motorcycle` (beta). The matrix service supports route costings except multimodal |
| Coverage | **India listed** among 40 two-wheeler countries | Worldwide (OSM data). Quality in our area must be tested | Whatever OSM extract we load. Geofabrik India is 1.6 GB, India Southern Zone 532 MB (data up to 2026-10-11) |
| Matrix limits | 625 elements/request; 3,000 elements/minute | **Not on Free or Starter.** 625 elements (Standard), 10,000 (Professional); batch into 25 × 25 tiles | Set by our own config |
| Pricing | Enterprise SKU: 1,000 free elements/month, then **$15 per 1,000** | 10 credits per matrix element. **Matrix requires Standard: $80/month for 7.5M credits** (+$0.02 per 1,000 extra); Professional $250. 14-day Professional trial for new accounts, no card | Software free (MIT licence). Pay for a server and our time |
| Map-display rights | Routes results **must be shown on a Google Map**, so Leaflet/OSM tiles are not allowed | Terms don't restrict Leaflet; Stadia markets its raster basemaps for Leaflet. Attribution must be kept | ODbL data: display anywhere with "© OpenStreetMap contributors" attribution |
| Storing results / offline | Most Routes content may not be cached (place IDs excepted) | **Server-side caching prohibited**; client-side caching only, ≤7 days without headers. No storage right for routing results (unlike geocoding). Storing our sequence and route totals is **unresolved** | Unrestricted for internal use (ODbL; share-alike applies only if we publicly distribute a derived database) |
| Production use | Allowed (paid) | Production needs a paid plan (Standard or higher for the matrix). §8 also prohibits **benchmarking against competitors** without written permission. New terms take effect 2026-11-09 | Allowed. No SLA except what we build |
| Hosting effort | None | None (API key) | A Docker image (`valhalla-scripted`) builds tiles from a PBF. We own the VM, monthly data refresh, monitoring and uptime |
| Switching risk | Different API shape | Same engine as option 3, so we can move to self-hosting later with little change | — |

Also checked and **not shortlisted**: GraphHopper hosted (has a `scooter` profile, ~50 km/h moped, but its free plan is non-commercial and limited to car/bike/foot; €69/€199/€479 per month plans; per-request location caps of 30/80/200 drive the plan choice; its storage/display terms could not be retrieved). Mapbox Matrix (profiles driving, walking, cycling, driving-traffic only; no two-wheeler). openrouteservice (car, HGV, cycling, foot, wheelchair; no two-wheeler). The OSRM public demo used in Phase 0 is not allowed for production. Self-hosted OSRM would need a custom Lua profile for motorbikes; Valhalla already has one.

## Cost estimates

**Assumptions** (the same volume model as `cost_projection.md`; all are assumptions, not measurements):
- One round per working day, **26 rounds/month**. Riders: 3 / 5 / 8 for 20 / 50 / 100 orders.
- Locations per round = orders + 2 starts + one distinct fixed end per rider. This is an upper bound; shared endpoints, Last stop and same-building grouping reduce it.
- The initial plan uses a full square matrix (origins × destinations, diagonal included). **2 reroutes per rider per round**, each a full matrix over origin + remaining stops + end. No reuse of stored matrices.
- Monthly elements: **21,866 / 97,214 / 348,296**. Billing tiers as published. USD unless noted. Excludes tax, map tiles/basemaps, geocoding and engineering time.

| Orders/day | Google `TWO_WHEELER` | Stadia Maps (10 credits/element) | Self-hosted Valhalla |
|---|---|---|---|
| 20 | **$312.99/month** | 218,660 credits → **$80/month** (Standard) | Server only (see below) |
| 50 | **$1,443.21/month** | 972,140 credits → **$80/month** (Standard) | Server only |
| 100 | **$4,464.55/month** | 3,482,960 credits → **$80/month** (Standard, 7.5M credits) | Server only |

**Self-hosted assumptions (not verified against any price list):** a cloud VM with ~4 vCPU and 8–16 GB RAM is enough to build and serve a city or the India Southern-Zone extract (Bengaluru is only our *test* area; the delivery area is undecided); we estimate **US$20–60/month**. Setup takes about 1–2 engineer-days, then roughly 1–2 hours/month for data refreshes and monitoring. Valhalla's docs give **no official hardware figures**, so the build time and memory must be measured in a trial before anyone relies on this.

## Recommendation (corrected for the ₹0 budget)

**Owner constraint (12 Oct 2026):** delivery area DU North Campus, Delhi; routing/service budget **₹0**; no paid subscriptions or billable services.

- **Primary candidate: self-hosted Valhalla on OpenStreetMap data** (`motor_scooter`; `motorcycle` beta). No per-request fee. ODbL data may be stored, displayed on Leaflet with attribution, and recorded as evidence. Now under local evaluation: see `VALHALLA-LOCAL.md` (in progress).
- **Stadia Maps: not recommended and inactive.** The matrix needs Standard ($80/month), which the budget excludes. In addition, storing our computed **sequence/assignment** (not just totals and ETAs) is **unresolved** under its terms, so an unconfirmed Stadia setup could not back persisted plans or offline lists. An earlier draft of this page suggested persisting the sequence while awaiting Stadia's answer; that was wrong and has been withdrawn.
- **Google Routes `TWO_WHEELER`: optional and inactive.** It is billable beyond the 1,000-element free cap, and its display rules exclude Leaflet.
- **Public demo servers** (OSRM demo used in Phase 0): research evidence only, never production.

Remaining costs of self-hosting are infrastructure and effort, not licences. Before a pilot, a ₹0 production host must be identified (an existing machine, or a free tier whose limits are verified), or the budget revisited. That is an owner decision.

## What acceptance needs for the selected provider (criterion 2)

Using public test points only:
- A live directed matrix with profile, timestamp, units, element count and response status recorded.
- At least one asymmetry or detour shown.
- Error-path tests around the real adapter.

For the ₹0 budget, criterion 2 is pursued with **local Valhalla** on public DU North Campus points (`VALHALLA-LOCAL.md` (in progress)). The Stadia adapter (27 mocked tests) stays unused; its live check is not planned.

## Sources (official, read 2026-10-12)

- Google: [two-wheeler routes](https://developers.google.com/maps/documentation/routes/route_two_wheel), [two-wheeler coverage](https://developers.google.com/maps/documentation/routes/coverage-two-wheeled), [usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing), [price list](https://developers.google.com/maps/billing-and-pricing/pricing), [policies](https://developers.google.com/maps/documentation/routes/policies), [computeRouteMatrix](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRouteMatrix)
- Stadia Maps: [pricing](https://stadiamaps.com/pricing/), [time-distance matrix](https://docs.stadiamaps.com/routing/time-distance-matrix/), [standard routing / service limits](https://docs.stadiamaps.com/routing/standard-routing/), [terms of service](https://stadiamaps.com/terms-of-service/)
- Valhalla: [route API costing models](https://valhalla.github.io/valhalla/api/route/api-reference/), [matrix API](https://valhalla.github.io/valhalla/api/matrix/), [repository (MIT)](https://github.com/valhalla/valhalla), [Docker README](https://github.com/valhalla/valhalla/blob/master/docker/README.md); [Geofabrik India extracts](https://download.geofabrik.de/asia/india.html)
- Others checked: [GraphHopper pricing](https://www.graphhopper.com/pricing/), [GraphHopper credits](https://support.graphhopper.com/support/solutions/articles/44000718211-what-is-one-credit-), [Mapbox Matrix](https://docs.mapbox.com/api/navigation/matrix/), [openrouteservice profiles](https://giscience.github.io/openrouteservice/technical-details/tag-filtering)
