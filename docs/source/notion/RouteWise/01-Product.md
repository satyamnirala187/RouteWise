# Product vision and confirmed scope

[Home](../RouteWise.md)

**Baseline:** current user's consolidated RouteWise requirements, carrying forward the earlier product discussion. **Implementation:** not started. Recommendations below are explicitly distinguished from agreed product behavior.

## Product promise

Give a startup a practical way to import daily deliveries, distribute them across riders and plan efficient routes that respect road travel, rider starts, capacities, priorities and independently chosen endpoints.

## Users and boundaries

| Admin | Rider |
|---|---|
| Secure login; review all orders and assignments | Secure login; see only own assigned deliveries |
| Upload Excel and edit imported customer details | Select and confirm own final destination |
| Configure scooter/bike, capacity and Office/Warehouse start | Tap contact to call; open Google Maps navigation |
| Choose equal, smart or manual assignment | Quick call to next customer |
| Set first-delivery priority and optimize all routes | Set Pending, Postponed or Completed per order |
| Review delivery status centrally | Reroute only own remaining orders and use saved data offline |

## Confirmed requirements

| ID | Requirement | Phase |
|---|---|---|
| R01 | Mobile-first PWA for Admin and Rider | 1, 3, 5 |
| R02 | Secure role authorization and secure sessions enforced by backend | 1 |
| R03 | Excel input: Name, Product, Contact, Location (Google Maps link) | 1 |
| R04 | Delivery Instructions is an optional fifth column | 1, 3 |
| R05 | Smart extraction and validation; resolve supported map links; manual pin/location fallback | 0, 1 |
| R06 | Editable customer orders as table/cards with product and contact detail | 1, 3 |
| R07 | Multiple riders, scooter/bike choice and capacities | 2 |
| R08 | Admin sets each rider's start to Office or Warehouse | 2 |
| R09 | Each rider chooses Office/Warehouse/Home/Last stop/Custom endpoint | 2, 3 |
| R10 | Initial optimization only after all participating riders confirm endpoints | 2 |
| R11 | Admin centrally optimizes using real road distances | 0, 2 |
| R12 | Equal, smart and manual delivery distribution | 2 |
| R13 | First-delivery priority | 2 |
| R14 | One-tap dialer and Google Maps Navigate | 3 |
| R15 | Quick call to next customer before travelling | 4 |
| R16 | Order statuses strictly Pending/Postponed/Completed | 1, 3 |
| R17 | Unavailable customer can be postponed; rider may reroute own remainder | 4 |
| R18 | Reroute origin is actual current location or explicitly selected last completed stop | 4 |
| R19 | Preserve other riders' package assignments during rider reroutes | 2, 4 |
| R20 | Same-building customers share one navigation stop with distinct orders/statuses | 4 |
| R21 | Save own rider list offline; queue status changes; synchronize on reconnect | 5 |
| R22 | Reoptimization requires connectivity | 4, 5 |
| R23 | Endpoint changes after planning trigger only that rider's reoptimization | 4 |
| R24 | Explicit privacy safeguards for customer contacts, locations and rider home endpoints | 1, 5 |

## Import contract

Required canonical headings: `Name`, `Product`, `Contact`, `Location (Google Maps link)`. Accept known heading aliases such as `Location (Maps Link)` through an explicit mapping preview. Optional: `Delivery Instructions`.

Preserve contact strings, including leading zeros and international prefixes. Trim incidental whitespace without rewriting customer names or products. Empty optional instructions are valid. Display row-level problems before committing imports. Do not execute Excel macros, formulas or arbitrary embedded URLs. Generate internal order identifiers; importing a row is not evidence that its pin is valid.

Coordinates must identify the destination, not merely the map camera center. Unsupported, ambiguous, inaccessible or shortened map links get a correction prompt. Optimization cannot proceed with unresolved required locations. Duplicate-looking rows must be reviewed rather than silently discarded: two orders at one address may be legitimate.

## Scope limits

The selected add-ons from the nine suggestions are only **#2 Delivery Instructions, #4 Quick Customer Availability Check, #8 Same-building Grouping and #9 Offline Support**.

Do not introduce fuel analytics, a separate postponed-orders management dashboard, a new balanced-workload mode, compulsory package confirmation or a compulsory dispatch-confirmation stage. Endpoint confirmation is required and is a different action. GPS tracking, payments, proof-of-delivery photos and customer notification services are not part of this baseline.

## Working defaults to validate in Phase 0

These resolve implementation details without claiming new user-approved features:

- Treat “bike” as motorbike, alongside scooters. Confirm vehicle profile coverage before selecting a provider; bicycle routing must not be silently used.
- Capacity is initially order count because the agreed import has no weight/volume fields. An order with several products is still one order. Revisit only through a documented scope decision.
- Equal mode targets near-equal order counts subject to capacity and constraints. Smart mode minimizes total road travel cost. Manual mode fixes admin assignments and optimizes sequence within each rider.
- Priority means the designated first order on a rider's route, not a guarantee that one rider delivers before all other riders in wall-clock time. Conflicting first priorities must be surfaced.
- Postponed orders stay visible and assigned but leave the active sequence until the rider explicitly returns them to Pending. No automatic retries. This policy needs a Phase 0 decision entry.
- A Home or Custom endpoint requires a resolved location. Last stop means an open route ending at the last delivery; it is not a fictitious depot.
- Keep package ownership fixed after a plan is issued during ordinary replanning. No new handover workflow is introduced. Any future transfer behavior requires separate approval.

## Success means

The admin can turn a validated sheet into feasible routes. Riders can complete their work with few taps and no cross-rider data access. Status changes survive reconnect without silent loss. The pilot demonstrates usability and measures route outcomes against a recorded baseline, without invented savings targets.
