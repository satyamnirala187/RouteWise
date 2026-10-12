# How RouteWise works

[Home](../RouteWise.md) · [Requirements](01-Product.md)

All screens and interactions described here are planned.

## 1. Sign in

Admin and Rider use the same branded login entry. The server authenticates the session and chooses permitted screens. A rider cannot gain access to other orders by changing a URL or request body.

## 2. Import and review

The admin uploads Excel, maps any supported heading aliases and reviews an editable order table. Each row shows Name, Product, Contact, Location, optional Delivery Instructions and its initial Pending status. Row errors and unresolved locations are visible. The admin corrects links or selects a pin, checks duplicate-looking rows, then saves the batch.

## 3. Configure the round

For every participating rider, the admin selects Scooter or Bike, capacity and **Office or Warehouse** start. The admin chooses equal/smart/manual distribution and any first-delivery priority. Saved Office and Warehouse coordinates must be validated. No real addresses are supplied in this package.

## 4. Riders confirm their own endpoints

Each rider selects **Office / Warehouse / Home / Last stop / Custom**. Home and Custom require resolved coordinates. The admin sees which endpoints are confirmed without exposing another rider's home address to riders. **Optimize all routes** remains unavailable while an active rider's endpoint is missing, invalid or unconfirmed. The backend enforces this gate as well.

This is destination confirmation only. There is no mandatory package-confirmation or dispatch-confirmation step.

## 5. Admin creates the initial plan

The server requests road matrices, applies capacities, fixed starts, endpoints and priorities, and finds a feasible distribution/sequence. The admin sees assignments and route summaries. An impossible plan explains the constraint conflict instead of dropping orders silently. Plan updates carry a version so a concurrent status change cannot overwrite newer work.

## 6. Rider delivers

A rider's list shows the assigned stop sequence and each customer's name, products, phone action, location and instructions. A prominent next-customer card offers **Call**, **Navigate**, and the three status choices. Call opens the phone dialer; Navigate opens Google Maps to the selected stop. Neither automatically completes an order.

Same-building stops expand into separate customer orders. Completing one customer's order leaves the others unchanged. Finish a stop only when no active Pending orders remain there; Postponed orders remain visible separately within the rider's list.

## 7. Customer is unavailable

The rider calls the next customer, marks that specific order **Postponed**, and can choose to reroute the remaining Pending orders. If the rider declines rerouting, retain the remaining order sequence and move to the next active order. If another Pending customer shares the current building, keep that navigation stop.

For rerouting, use a freshly obtained current position with user location permission. If unavailable or declined, offer the last completed stop and explicitly label that fallback. Before any completed stop exists, ask the rider to confirm a current pin or their configured start rather than pretending GPS is available. Other riders' orders, sequences and endpoint selections stay unchanged.

Proposed return behavior: the rider changes a Postponed order back to Pending when available and requests a new sequence. Phase 0 will confirm this rule.

## 8. Rider changes final destination

Save the new endpoint selection and request that rider's online reoptimization, preserving completed orders and all assignments. If the request fails, keep the last valid plan visibly marked as awaiting recalculation. An offline change can be retained locally as an unconfirmed draft, but it must not be presented as an optimized route. Reconcile pending status updates before calculating a replacement route.

## 9. Connection drops

The previously saved own-rider list remains accessible, with a last-synced timestamp. Local status changes update the display and are marked **waiting to sync** beside the order; this is sync metadata, not a fourth order status. Reoptimization is disabled with a clear connectivity message. Offline maps, live traffic and Google Maps navigation availability are not promised by RouteWise.

On reconnect, authenticate, reconcile the ordered status queue using unique operation IDs and versions, then refresh the list. Conflicts are shown rather than overwriting Completed with an older Pending update. Do not rely on background sync while the app is closed; foreground reopen/reconnect must work on supported mobile browsers.

## Illustrative round

Two synthetic riders have different starts and endpoints. Orders A and B share Building X; C is at Building Y. Rider 1 receives A and B and Rider 2 receives C. Rider 1 navigates once to X, completes A, postpones B, and reroutes toward their endpoint or other Pending stops. Rider 2's C assignment and route remain untouched. Returning B to Pending later does not change its owner.
