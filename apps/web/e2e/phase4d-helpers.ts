// Shared helpers for the step 4D browser specs: the rider's own "Recalculate my route" and shared stops.
//
// MOCKED GEOLOCATION. No phone and no GPS is involved anywhere in these tests. A device position is either
// emulated by the browser itself (Playwright `grantPermissions` + `setGeolocation`, which still goes through
// the real `navigator.geolocation` and the browser's permission) or replaced by a scripted stub for the cases
// a browser cannot produce on demand (timeout, unavailable, an old or inaccurate fix). Plans use the RECORDED
// real local-Valhalla DU matrices unless ROUTEWISE_E2E_LIVE=1. Customers are synthetic; points are public.
import { expect, type Browser, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Api, ensureDepots, gotoRound, newPage, prepareRound, riderIds, signIn, WEB, P } from "./phase2-helpers";
import { guardExternal, newRound, plan } from "./phase3-helpers";

const FIXTURE = JSON.parse(readFileSync(path.resolve(import.meta.dirname, "../../../tests/fixtures/public_locations_du_north.json"), "utf8")).locations as
  { id: string; lat: number; lng: number }[];
export const PT: Record<string, { lat: number; lng: number }> = Object.fromEntries(FIXTURE.map((l) => [l.id, { lat: l.lat, lng: l.lng }]));
/** The public point used as the MOCKED device position (inside the DU North Campus service area and in the recorded matrices). */
export const GPS = PT.gps_r1;
/** In the service area but not in the recorded matrices: a real run from here fails (the recorded provider has no road data for it). */
export const UNRECORDED = { lat: GPS.lat + 0.0004, lng: GPS.lng };
/** Resolved coordinates far outside the service area. */
export const FAR = { lat: 19.076, lng: 72.8777 };

export type GeoStub =
  | { kind: "fix"; lat: number; lng: number; accuracy?: number; ageMs?: number }
  | { kind: "error"; code: 1 | 2 | 3 }
  | { kind: "hang" };

export interface GeoLog { get: number; watch: number; options: PositionOptions[] }

/** Install the geolocation mock before the page's own scripts run. `stub` replaces `getCurrentPosition`; without one the browser's
 * emulated geolocation answers. Every call is counted (`window.__geo`), and `watchPosition` is made to fail loudly: the app must never track. */
export async function installGeolocation(page: Page, opts: { stub?: GeoStub; insecure?: boolean; absent?: boolean } = {}) {
  await page.context().addInitScript(({ stub, insecure, absent }) => {
    const log = { get: 0, watch: 0, options: [] as unknown[] };
    (window as unknown as { __geo: unknown }).__geo = log;
    if (insecure) Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
    if (absent) { Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true }); return; }
    const geo = navigator.geolocation;
    const real = geo.getCurrentPosition.bind(geo);
    geo.getCurrentPosition = (ok: PositionCallback, err?: PositionErrorCallback | null, options?: PositionOptions) => {
      log.get += 1; log.options.push(options);
      if (!stub) return real(ok, err ?? undefined, options);
      if (stub.kind === "hang") return;
      setTimeout(() => {
        if (stub.kind === "error") err?.({ code: stub.code, message: "mocked", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 } as GeolocationPositionError);
        else ok({ coords: { latitude: stub.lat, longitude: stub.lng, accuracy: stub.accuracy ?? 15 }, timestamp: Date.now() - (stub.ageMs ?? 0) } as GeolocationPosition);
      }, 20);
    };
    geo.watchPosition = () => { log.watch += 1; throw new Error("watchPosition must never be used"); };
  }, { stub: opts.stub ?? null, insecure: !!opts.insecure, absent: !!opts.absent });
}

export const geoLog = (page: Page) => page.evaluate(() => (window as unknown as { __geo: GeoLog }).__geo);

/** Let the browser's emulated geolocation answer at this point (mocked geolocation, still through `navigator.geolocation`). */
export async function emulateGeolocation(page: Page, at: { lat: number; lng: number }, accuracy = 20) {
  await page.context().grantPermissions(["geolocation"], { origin: WEB });
  await page.context().setGeolocation({ latitude: at.lat, longitude: at.lng, accuracy });
}

export interface Round { admin: Api; rid: string; routes: Record<string, string[]> }

/** A fresh round with riders Asha (Home) and Bilal (Last stop), planned: the starting point of nearly every 4D test. */
export async function plannedRound(): Promise<Round> {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "last_stop" }]);
  const routes = await plan(admin, rid);
  return { admin, rid, routes };
}

/** A signed-in rider page on one round with the 4D mocks installed, external links guarded and request counts kept. */
export async function openRider(browser: Browser, user: string, rid: string, geo: Parameters<typeof installGeolocation>[1] = {}) {
  const rp = await newPage(browser);
  await installGeolocation(rp, geo);
  const external = await guardExternal(rp);
  const posts: { url: string; body: string | null }[] = [];
  rp.on("request", (r) => { if (r.method() === "POST" && /\/api\/rider\/rounds\/[^/]+\/reroute$/.test(r.url())) posts.push({ url: r.url(), body: r.postData() }); });
  const consoleErrors: string[] = [];
  rp.on("console", (m) => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) consoleErrors.push(m.text()); });
  rp.on("pageerror", (e) => consoleErrors.push(String(e)));
  await signIn(rp, user);
  await gotoRound(rp, "/rider", rid);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", rid);
  return { rp, external, posts, consoleErrors };
}

export interface RiderView {
  plan: { version: number; rider_route: { revision: { number: number; trigger: string; origin_kind: string } | null; awaiting_recalculation: string | null;
    destination: { kind: string }; road_distance_m: number } | null } | null;
  sequence: { seq: number; customers: number; shared: boolean; orders: { id: string; order_code: string; status: string; version: number }[] }[];
  unsequenced: { order_code: string }[]; postponed: { order_code: string }[]; completed: { order_code: string }[];
  reroute: { available: boolean; in_progress_run_id: string | null; last_completed_stop: { order_code: string } | null; configured_start_allowed: boolean } | null;
}
export const viewOf = (api: Api, rid: string) => api.json<RiderView>(`/api/rider/rounds/${rid}/deliveries`);
export const sequenceCodes = (v: RiderView) => v.sequence.flatMap((s) => s.orders.map((o) => o.order_code));

/** A rider's API session by username (independent of any page). */
export const riderApi = (user: string) => Api.login(user);

// ---- locators (the section and its parts)
export const section = (p: Page) => p.getByTestId("reroute");
export const result = (p: Page) => p.getByTestId("reroute-result");
export const openChooser = async (p: Page) => { await p.getByTestId("reroute-open").click(); await expect(p.getByTestId("reroute-choices")).toBeVisible(); };

/** Hold the rider's recalculation by delaying only the matrix step (the e2e hold seam); always release in afterEach. */
export { hold } from "./phase2-helpers";

export { riderIds, P };
