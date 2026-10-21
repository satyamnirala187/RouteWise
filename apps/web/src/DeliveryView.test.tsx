import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DeliveryItem, DeliveryView as View, Status } from "./api";
import DeliveryView, { type StatusActions } from "./components/DeliveryView";

afterEach(cleanup);   // vitest has no globals here, so the library does not clean up by itself

const item = (code: string, status: Status = "Pending", over: Partial<DeliveryItem> = {}): DeliveryItem => ({
  id: `id-${code}`, order_code: code, customer_name: `Customer ${code}`, product: "Synthetic parcel", contact: "0000000001",
  instructions: null, status, version: 1, location: { lat: 28.69, lng: 77.21 }, location_issue: null, ...over,
});
const stop = (seq: number, orders: DeliveryItem[], shared = orders.length > 1): View["sequence"][number] => ({
  seq, orders, customers: orders.filter((o) => o.status === "Pending").length, shared,
  location: orders[0]?.location ?? null, location_issue: null,
});
const route = { vehicle: "scooter" as const, start: { kind: "office" as const, label: "Office" }, destination: { kind: "home" as const, label: null }, open_route: false, road_distance_m: 5000, road_duration_s: 600 };
const plan = (over: Partial<NonNullable<View["plan"]>> = {}): NonNullable<View["plan"]> => ({
  version: 1, is_current: true, created_at: "2026-10-20T08:00:00Z", out_of_date: false, progress_since_plan: false, superseded_versions: 0,
  real_road: true, recorded: true, route, rider_route: null, ...over,
});
const effective = (over: Partial<NonNullable<NonNullable<View["plan"]>["rider_route"]>> = {}) => ({
  revision: null, origin_label: null, vehicle: "scooter" as const, destination: { kind: "home" as const, label: null }, open_route: false,
  road_distance_m: 5000, road_duration_s: 600, awaiting_recalculation: null, ...over,
});
const view = (parts: Partial<View>): View => ({
  round_id: "r", round_name: "Round", participating: true,
  setup: { start: { kind: "office", label: "Office" }, destination: { kind: "home", label: null }, vehicle: "scooter", confirmation: "confirmed" },
  plan: plan(), sequence: [], unsequenced: [], postponed: [], completed: [], reroute: null, ...parts,
});

describe("shared stops", () => {
  const shared = view({ sequence: [stop(1, [item("B"), item("A")]), stop(2, [item("C")])] });

  it("render one container per stop with its customer count and exactly one Navigate for a shared stop", () => {
    render(<DeliveryView view={shared} />);
    const stops = screen.getAllByTestId("rider-stop");
    expect(stops.map((s) => s.getAttribute("data-customers"))).toEqual(["2", "1"]);
    const first = within(stops[0]);
    expect(first.getByTestId("stop-customers").textContent).toBe("2 customers at this location");
    expect(first.getAllByTestId("navigate-link")).toHaveLength(1);
    expect(first.getAllByTestId("navigate-link")[0].getAttribute("href")).toContain("destination=28.690000%2C77.210000");
    expect(first.getAllByTestId("rider-order")).toHaveLength(2);
    expect(first.getAllByTestId("call-link")).toHaveLength(2);                          // each customer keeps their own Call
    expect(within(first.getAllByTestId("rider-order")[0]).queryByTestId("navigate-link")).toBeNull();
    expect(within(stops[1]).getAllByTestId("navigate-link")).toHaveLength(1);           // a one-customer stop: its one Navigate
  });

  it("keep the server's order of customers inside the stop (priority customers lead)", () => {
    render(<DeliveryView view={shared} />);
    const cards = within(screen.getAllByTestId("rider-stop")[0]).getAllByTestId("rider-order");
    expect(cards.map((c) => c.getAttribute("data-order"))).toEqual(["B", "A"]);
    expect(within(cards[0]).getByTestId("next-customer-badge")).toBeTruthy();
    expect(within(cards[1]).queryByTestId("next-customer-badge")).toBeNull();
  });

  it("never merge two stops that merely share a pin", () => {
    const v = view({ sequence: [stop(1, [item("A")], false), stop(2, [item("B")], false)] });
    render(<DeliveryView view={v} />);
    expect(screen.getAllByTestId("rider-stop")).toHaveLength(2);
    expect(screen.queryByTestId("stop-customers")).toBeNull();
    expect(screen.getAllByTestId("navigate-link")).toHaveLength(2);
  });

  it("show the stop's own location problem once, with no Navigate, when its customers no longer share a valid pin", () => {
    const broken = { ...stop(1, [item("A"), item("B")]), location: null, location_issue: "The customers at this stop no longer share one valid pin; ask your admin to check them." };
    render(<DeliveryView view={view({ sequence: [broken] })} />);
    expect(screen.queryByTestId("navigate-link")).toBeNull();
    expect(screen.getAllByTestId("navigate-unavailable")).toHaveLength(1);
    expect(screen.getByTestId("navigate-unavailable").textContent).toContain("no longer share one valid pin");
  });

  it("note a shared location whose other customers are no longer Pending, keeping its one Navigate", () => {
    const v = view({ sequence: [stop(1, [item("A")], true)], completed: [item("X", "Completed")] });
    render(<DeliveryView view={v} />);
    expect(screen.getByTestId("shared-note").textContent).toContain("not Pending now");
    expect(screen.getAllByTestId("navigate-link")).toHaveLength(1);
  });
});

describe("the Route card", () => {
  it("keeps its wording without a recalculation", () => {
    render(<DeliveryView view={view({ plan: plan({ rider_route: effective() }), sequence: [stop(1, [item("A")])] })} />);
    expect(screen.getByTestId("route-distance").textContent).toContain("Planned road distance for the whole saved route 5.0 km");
    expect(screen.getByTestId("route-distance").textContent).toContain("This is the plan, not the distance left.");
    expect(screen.queryByTestId("route-revision")).toBeNull();
  });

  it("reads the rider's own revision: its number, origin and a planned total that is not the distance left", () => {
    const rider_route = effective({ revision: { number: 2, trigger: "rider_request", origin_kind: "last_completed_stop", origin_order_code: "A", created_at: "2026-10-20T09:15:00Z" },
      origin_label: "your last completed stop, not your current position", road_distance_m: 3200, road_duration_s: 420 });
    render(<DeliveryView view={view({ plan: plan({ rider_route }), sequence: [stop(1, [item("B")])] })} />);
    expect(screen.getByTestId("route-revision").textContent).toContain("Your route: revision 2");
    expect(screen.getByTestId("route-revision").textContent).toContain("your last completed stop, not your current position");
    const distance = screen.getByTestId("route-distance").textContent!;
    expect(distance).toContain("revision 2 of your route 3.2 km");
    expect(distance).toContain("traffic-free estimate");
    expect(distance).toContain("not the distance left");
  });

  it("says the saved route still ends at the previous destination, also for new coordinates under the same kind", () => {
    const base = { sequence: [stop(1, [item("A")])] };
    const moved = view({ ...base, plan: plan({ rider_route: effective({ awaiting_recalculation: "destination_changed" }) }) });
    const { unmount } = render(<DeliveryView view={moved} />);
    expect(screen.getByTestId("route-awaiting").textContent).toContain("changed the location of your Home destination");
    expect(screen.getByTestId("route-awaiting").textContent).toContain("still ends at the previous Home location until you recalculate");
    unmount();
    const kind = view({ ...base, setup: { ...moved.setup!, destination: { kind: "warehouse", label: "Warehouse" } },
      plan: plan({ rider_route: effective({ awaiting_recalculation: "destination_changed" }) }) });
    render(<DeliveryView view={kind} />);
    expect(screen.getByTestId("route-awaiting").textContent).toContain("You changed your destination to Warehouse. Your saved route still ends at Home until you recalculate.");
  });
});

describe("status actions while the route is recalculated", () => {
  it("are all disabled", () => {
    const actions: StatusActions = { saving: null, blocked: true, confirming: null, failed: null, change: vi.fn(), confirm: vi.fn(), retry: vi.fn() };
    render(<DeliveryView view={view({ sequence: [stop(1, [item("A"), item("B")]), stop(2, [item("C")])] })} actions={actions} />);
    const buttons = [...screen.getAllByRole("button")];
    expect(buttons.length).toBeGreaterThan(4);
    for (const b of buttons) expect((b as HTMLButtonElement).disabled).toBe(true);
  });
});
