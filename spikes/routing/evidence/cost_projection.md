# Matrix volume and cost projection

Generated 2026-10-12T16:14:17+00:00. Assumptions: 26 rounds/month; 2 reroutes per rider per round; locations = orders + 2 starts + 1 distinct fixed end per rider (upper bound); elements = origins × destinations; ≤625 elements per request. Prices: Google Maps Platform global list, USD, page updated 2026-10-08; free monthly caps applied per SKU. Monthly cost uses the no-reuse column.

| Orders | Riders | Locations | Initial elements (requests) | Per round, no reuse | Per round, origin-row reuse | Monthly elements (no reuse) | Enterprise (TWO_WHEELER) USD/month | Pro (traffic-aware) USD/month | Essentials (DRIVE, basic) USD/month |
|---|---|---|---|---|---|---|---|---|---|
| 20 | 3 | 25 | 625 (1) | 841 | 655 | 21,866 | 312.99 | 168.66 | 59.33 |
| 50 | 5 | 57 | 3,249 (9) | 3,739 | 3,309 | 97,214 | 1,443.21 | 922.14 | 436.07 |
| 100 | 8 | 110 | 12,100 (25) | 13,396 | 12,228 | 348,296 | 4,464.55 | 2,936.37 | 1,443.18 |

SKUs: Enterprise (TWO_WHEELER): 1,000 free elements/month; Pro (traffic-aware): 5,000 free elements/month; Essentials (DRIVE, basic): 10,000 free elements/month
