// Step 4A: which customer the rider should call next. Read-only: it only looks at the
// server-confirmed delivery view, so "next" changes only after the server has saved a change.

import type { DeliveryItem, DeliveryView } from "./api";

export type NextDelivery =
  | { kind: "next"; item: DeliveryItem; stop: number; others: number; stale: boolean }
  | { kind: "unsequenced"; count: number; planned: boolean }  // Pending orders, none in the saved route order
  | { kind: "postponed_only"; count: number }
  | { kind: "done" }   // every order the rider holds in this round is Completed
  | { kind: "none" };  // no deliveries in this round at all

/** The first Pending order of the first saved stop that still has one. Only the saved
 * sequence is used: an order outside it is never picked, and Postponed or Completed orders
 * are never "next" even if a stale view listed them in a stop. */
export function nextDelivery(view: DeliveryView): NextDelivery {
  for (const stop of view.sequence) {
    const pending = stop.orders.filter((o) => o.status === "Pending");
    if (pending.length > 0) {
      return { kind: "next", item: pending[0], stop: stop.seq, others: pending.length - 1, stale: !!view.plan?.out_of_date };
    }
  }
  const unsequenced = view.unsequenced.filter((o) => o.status === "Pending").length;
  if (unsequenced > 0) return { kind: "unsequenced", count: unsequenced, planned: !!view.plan };
  if (view.postponed.length > 0) return { kind: "postponed_only", count: view.postponed.length };
  if (view.completed.length > 0) return { kind: "done" };
  return { kind: "none" };
}
