import { describe, expect, it, vi } from "vitest";
import { ApiError, type DeliveryView } from "./api";
import {
  awaitingText, describeRefusal, describeRun, expectedOf, locationSupport, originBody, PositionError, readCurrentPosition,
  type GpsLimits, type RunSummary,
} from "./reroute";

const LIMITS: GpsLimits = { max_accuracy_m: 100, max_age_s: 60 };
const NOW = 1_800_000_000_000;

/** A fake `navigator.geolocation` (mocked geolocation: no device is involved). */
function geo(behaviour: (ok: PositionCallback, err: PositionErrorCallback, opts?: PositionOptions) => void) {
  const getCurrentPosition = vi.fn(behaviour);
  const watchPosition = vi.fn(() => { throw new Error("watchPosition must never be used"); });
  return { nav: { geolocation: { getCurrentPosition, watchPosition } as unknown as Geolocation }, getCurrentPosition, watchPosition };
}
const fix = (accuracy: number, ageMs = 0, lat = 28.688345, lng = 77.214788) =>
  ({ coords: { latitude: lat, longitude: lng, accuracy }, timestamp: NOW - ageMs }) as GeolocationPosition;
const read = (g: ReturnType<typeof geo>, extra: { signal?: AbortSignal } = {}) =>
  readCurrentPosition(LIMITS, { signal: extra.signal ?? new AbortController().signal, win: { isSecureContext: true }, nav: g.nav, now: () => NOW });

describe("location availability", () => {
  it("is refused on an insecure page even though the browser exposes the API", () => {
    expect(locationSupport({ isSecureContext: false }, { geolocation: {} })).toBe("insecure");
  });
  it("is unsupported without a geolocation API and ok on a secure page with one", () => {
    expect(locationSupport({ isSecureContext: true }, {})).toBe("unsupported");
    expect(locationSupport({ isSecureContext: true }, { geolocation: {} })).toBe("ok");
  });
  it("is blocked, not denied, when the document's own Permissions-Policy forbids location", () => {
    const allows = (v: boolean) => ({ allowsFeature: (f: string) => f !== "geolocation" || v });
    expect(locationSupport({ isSecureContext: true }, { geolocation: {} }, { permissionsPolicy: allows(false) })).toBe("blocked");
    expect(locationSupport({ isSecureContext: true }, { geolocation: {} }, { featurePolicy: allows(false) })).toBe("blocked");
    expect(locationSupport({ isSecureContext: true }, { geolocation: {} }, { permissionsPolicy: allows(true) })).toBe("ok");
    expect(locationSupport({ isSecureContext: true }, { geolocation: {} }, {})).toBe("ok");   // a browser that cannot tell
  });
  it("never asks the browser when the page blocks location, and does not claim the rider refused", async () => {
    const g = geo((ok) => ok(fix(10)));
    const err = await readCurrentPosition(LIMITS, { signal: new AbortController().signal, win: { isSecureContext: true }, nav: g.nav,
      doc: { permissionsPolicy: { allowsFeature: () => false } } }).catch((e) => e);
    expect(err).toMatchObject({ problem: "blocked" });
    expect(g.getCurrentPosition).not.toHaveBeenCalled();
    expect(err.message).not.toMatch(/denied|you (chose|refused)/i);
  });
  it("never asks the browser on an insecure page", async () => {
    const g = geo((ok) => ok(fix(10)));
    await expect(readCurrentPosition(LIMITS, { signal: new AbortController().signal, win: { isSecureContext: false }, nav: g.nav }))
      .rejects.toMatchObject({ problem: "insecure" });
    expect(g.getCurrentPosition).not.toHaveBeenCalled();
  });
});

describe("one fresh device position", () => {
  it("asks once, with high accuracy, no cached position and a bounded wait; never watches", async () => {
    const g = geo((ok) => ok(fix(12, 2000)));
    const f = await read(g);
    expect(f).toEqual({ lat: 28.688345, lng: 77.214788, accuracy_m: 12, age_s: 2 });
    expect(g.getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(g.getCurrentPosition.mock.calls[0][2]).toEqual({ enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
    expect(g.watchPosition).not.toHaveBeenCalled();
  });

  it.each([[1, "denied"], [2, "unavailable"], [3, "timeout"]] as const)("maps the browser's error code %i to %s", async (code, problem) => {
    const g = geo((_ok, err) => err({ code, message: "x" } as GeolocationPositionError));
    await expect(read(g)).rejects.toMatchObject({ name: "PositionError", problem });
  });

  it("refuses an inaccurate or an old position using the server's limits, without sending anything", async () => {
    await expect(read(geo((ok) => ok(fix(250))))).rejects.toMatchObject({ problem: "inaccurate" });
    await expect(read(geo((ok) => ok(fix(10, 120_000))))).rejects.toMatchObject({ problem: "stale" });
    await expect(read(geo((ok) => ok(fix(Number.NaN))))).rejects.toMatchObject({ problem: "invalid" });
    await expect(read(geo((ok) => ok(fix(10, 0, 123, 0))))).rejects.toMatchObject({ problem: "invalid" });
  });

  it("never puts a coordinate into any message it shows", async () => {
    const shown: string[] = [];
    for (const behaviour of [
      (ok: PositionCallback) => ok(fix(250, 0, 28.688345, 77.214788)),
      (ok: PositionCallback) => ok(fix(10, 120_000, 28.688345, 77.214788)),
      (_ok: PositionCallback, err: PositionErrorCallback) => err({ code: 1 } as GeolocationPositionError),
    ]) {
      const e = await read(geo(behaviour)).catch((x: unknown) => x);
      expect(e).toBeInstanceOf(PositionError);
      shown.push((e as PositionError).message);
    }
    for (const text of shown) expect(text).not.toMatch(/28\.68|77\.21/);
  });

  it("can be cancelled, and a late answer is then ignored", async () => {
    let answer!: PositionCallback;
    const g = geo((ok) => { answer = ok; });
    const ac = new AbortController();
    const p = read(g, { signal: ac.signal });
    ac.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
    answer(fix(5));   // the phone answers after the cancel: nothing happens
    expect(g.getCurrentPosition).toHaveBeenCalledTimes(1);
  });
});

describe("request bodies", () => {
  const exp = { plan: 2, revision: 1 };
  it("send coordinates only for a current position and name the order only for the last completed stop", () => {
    const f = { lat: 28.69, lng: 77.21, accuracy_m: 9, age_s: 1 };
    expect(originBody("current_position", exp, { fix: f })).toEqual({ origin: { kind: "current_position", ...f }, expected_plan_version: 2, expected_revision: 1 });
    expect(originBody("last_completed_stop", exp, { orderId: "o1", fix: f })).toEqual({ origin: { kind: "last_completed_stop", order_id: "o1" }, expected_plan_version: 2, expected_revision: 1 });
    expect(originBody("configured_start", exp, { orderId: "o1", fix: f })).toEqual({ origin: { kind: "configured_start" }, expected_plan_version: 2, expected_revision: 1 });
  });
  it("carry the plan version and revision the rider was looking at (0 = the plan's own route)", () => {
    const v = { plan: { version: 3, rider_route: null } } as unknown as DeliveryView;
    expect(expectedOf(v)).toEqual({ plan: 3, revision: 0 });
    expect(expectedOf({ plan: null } as unknown as DeliveryView)).toBeNull();
  });
});

describe("refusals and run outcomes", () => {
  const refused = (status: number, code: string, details: string[] = []) => new ApiError(status, `message for ${code}`, { code, message: `message for ${code}`, details });

  it("follows an existing run instead of starting another", () => {
    expect(describeRefusal(refused(409, "REROUTE_IN_PROGRESS", ["run-1"]))).toMatchObject({ followRun: "run-1", retry: false });
  });
  it("says busy, bad position and changed-state refusals differently and always says the route is unchanged", () => {
    expect(describeRefusal(refused(503, "PLANNING_BUSY"))).toMatchObject({ retry: true, reload: false });
    expect(describeRefusal(refused(422, "POSITION_UNUSABLE"))).toMatchObject({ retry: true, text: "message for POSITION_UNUSABLE Your route is unchanged." });
    const changed = describeRefusal(refused(409, "ROUTE_CHANGED"));
    expect(changed).toMatchObject({ reload: true, retry: false });
    expect(changed.text).toContain("Your route is unchanged");
  });

  const run = (state: RunSummary["state"], code?: string): RunSummary => ({
    state, revision: state === "succeeded" ? 2 : null, origin_kind: "configured_start",
    error: code ? { code, message: "server text", details: [] } : null,
  });
  it("distinguishes failed, stale and interrupted runs and keeps the previous route in all three", () => {
    for (const [state, code, kind] of [["failed", "UNROUTABLE_ORIGIN", "failed"], ["stale", "INPUTS_CHANGED", "stale"], ["interrupted", "INTERRUPTED", "interrupted"]] as const) {
      const o = describeRun(run(state, code));
      expect(o).toMatchObject({ kind });
      expect((o as { text: string }).text).toContain("Your previous route is still shown.");
    }
    expect((describeRun(run("failed", "UNROUTABLE_ORIGIN")) as { text: string }).text).toContain("No road was found near that starting point");
    expect(describeRun(run("succeeded"))).toEqual({ kind: "succeeded" });
    expect((describeRun(run("stale", "ROUND_REPLANNED")) as { reload: boolean }).reload).toBe(true);
  });
});

describe("destination changed after the route was saved", () => {
  const view = (saved: string, now: string, awaiting: "destination_changed" | null) => ({
    setup: { destination: { kind: now } }, plan: { rider_route: { destination: { kind: saved }, awaiting_recalculation: awaiting } },
  }) as unknown as DeliveryView;
  it("names the previous destination when the kind changed", () => {
    expect(awaitingText(view("office", "warehouse", "destination_changed")))
      .toBe("You changed your destination to Warehouse. Your saved route still ends at Office until you recalculate.");
  });
  it("detects new Home coordinates under the same kind from the server's metadata alone", () => {
    expect(awaitingText(view("home", "home", "destination_changed"))).toContain("changed the location of your Home destination");
  });
  it("says nothing when the server reports nothing awaiting", () => {
    expect(awaitingText(view("office", "office", null))).toBeNull();
  });
});
