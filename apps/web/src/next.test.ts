import { describe, expect, it } from "vitest";
import type { DeliveryItem, DeliveryView, Status } from "./api";
import { nextDelivery } from "./next";

const item = (code: string, status: Status = "Pending"): DeliveryItem => ({
  id: `id-${code}`, order_code: code, customer_name: `Customer ${code}`, product: "Synthetic parcel", contact: "0000000001",
  instructions: null, status, version: 1, location: { lat: 28.69, lng: 77.21 }, location_issue: null,
});
/** A saved stop with the 4C shared-stop fields (the server sends them for every stop). */
const stop = (seq: number, orders: DeliveryItem[]): DeliveryView["sequence"][number] => ({
  seq, orders, customers: orders.filter((o) => o.status === "Pending").length, shared: orders.length > 1,
  location: orders[0]?.location ?? null, location_issue: null,
});
const plan = (out_of_date = false): DeliveryView["plan"] => ({
  version: 1, is_current: true, created_at: "2026-10-19T00:00:00Z", out_of_date, progress_since_plan: false,
  superseded_versions: 0, real_road: true, recorded: true, route: null, rider_route: null,
});
const view = (parts: Partial<DeliveryView>): DeliveryView => ({
  round_id: "r", round_name: "Round", participating: true, setup: null, plan: plan(),
  sequence: [], unsequenced: [], postponed: [], completed: [], reroute: null, ...parts,
});

describe("nextDelivery", () => {
  it("is the first Pending order of the first saved stop", () => {
    const v = view({ sequence: [stop(1, [item("A")]), stop(2, [item("B")])] });
    expect(nextDelivery(v)).toMatchObject({ kind: "next", stop: 1, others: 0, stale: false, item: { order_code: "A" } });
  });
  it("keeps the saved stop number and counts other Pending customers at the same stop", () => {
    const v = view({ sequence: [stop(3, [item("C"), item("D")]), stop(4, [item("E")])] });
    expect(nextDelivery(v)).toMatchObject({ kind: "next", stop: 3, others: 1, item: { order_code: "C" } });
  });
  it("never picks a Postponed or Completed order, even if a view listed one in a stop", () => {
    const v = view({ sequence: [stop(1, [item("A", "Completed"), item("B", "Postponed")]), stop(2, [item("C")])] });
    expect(nextDelivery(v)).toMatchObject({ kind: "next", stop: 2, item: { order_code: "C" } });
  });
  it("marks an out-of-date saved route as stale instead of implying a fresh optimization", () => {
    const v = view({ plan: plan(true), sequence: [stop(3, [item("C")])] });
    expect(nextDelivery(v)).toMatchObject({ kind: "next", stale: true, stop: 3 });
  });
  it("does not choose an order outside the saved sequence", () => {
    const v = view({ unsequenced: [item("U1"), item("U2")], postponed: [item("P", "Postponed")] });
    expect(nextDelivery(v)).toEqual({ kind: "unsequenced", count: 2, planned: true });
    expect(nextDelivery({ ...v, plan: null })).toEqual({ kind: "unsequenced", count: 2, planned: false });
  });
  it("reports the empty states", () => {
    expect(nextDelivery(view({ postponed: [item("P", "Postponed")], completed: [item("X", "Completed")] })))
      .toEqual({ kind: "postponed_only", count: 1 });
    expect(nextDelivery(view({ completed: [item("X", "Completed")] }))).toEqual({ kind: "done" });
    expect(nextDelivery(view({}))).toEqual({ kind: "none" });
    expect(nextDelivery(view({ plan: null }))).toEqual({ kind: "none" });
  });
});
