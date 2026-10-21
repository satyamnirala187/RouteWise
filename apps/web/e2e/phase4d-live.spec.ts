// Opt-in: the rider's own recalculation in the browser on the REAL local Valhalla tiles (no recorded matrices).
//   ROUTEWISE_E2E_LIVE=1 E2E_4D_SHOTS_DIR=<scratch> scripts/e2e.sh e2e/phase4d-live.spec.ts
// Needs spikes/valhalla/data/valhalla_tiles. The device position is MOCKED geolocation (emulated by the browser at a public
// point inside the service area); no phone or real GPS is involved. Customers are synthetic; points are public OSM points.
import { expect, test } from "@playwright/test";
import { Api } from "./phase2-helpers";
import { codesShown, shooter } from "./phase3-helpers";
import { emulateGeolocation, geoLog, GPS, openChooser, openRider, plannedRound, result, riderApi, sequenceCodes, viewOf } from "./phase4d-helpers";

test.skip(process.env.ROUTEWISE_E2E_LIVE !== "1", "set ROUTEWISE_E2E_LIVE=1 to recalculate on the real local Valhalla tiles");

const shot = shooter("E2E_4D_SHOTS_DIR", "4d", "phase4");

test("live: a rider recalculates from a mocked device position on real local Valhalla roads", async ({ browser }) => {
  const { admin, rid, routes } = await plannedRound();                      // the plan itself is live too
  const planView = await viewOf(await riderApi("p2_asha"), rid);
  const { rp } = await openRider(browser, "p2_asha", rid);
  await emulateGeolocation(rp, GPS);                                        // MOCKED geolocation
  await openChooser(rp);
  const started = Date.now();
  await rp.getByTestId("reroute-current").click();
  await expect(result(rp)).toContainText("Route recalculated from your current position (device location)", { timeout: 120_000 });
  const elapsed = (Date.now() - started) / 1000;
  const me = await Api.of(rp);
  const view = await me.json<{ plan: { real_road: boolean; recorded: boolean; rider_route: { revision: { number: number; origin_kind: string }; road_distance_m: number; road_duration_s: number } } }>(
    `/api/rider/rounds/${rid}/deliveries`);
  expect(view.plan.real_road).toBe(true);
  expect(view.plan.recorded).toBe(false);                                   // real tiles, not a replayed recording
  expect(view.plan.rider_route.revision).toMatchObject({ number: 1, origin_kind: "current_position" });
  expect(view.plan.rider_route.road_distance_m).toBeGreaterThan(0);
  expect([...sequenceCodes(await viewOf(me, rid))].sort()).toEqual([...routes.Asha].sort());
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(sequenceCodes(await viewOf(me, rid)));
  expect((await geoLog(rp)).get).toBe(1);
  console.log("LIVE-BROWSER-REROUTE", JSON.stringify({
    project: test.info().project.name, device_position: "mocked geolocation (emulated by the browser)", real_road: view.plan.real_road,
    recorded: view.plan.recorded, origin_kind: view.plan.rider_route.revision.origin_kind, stops: sequenceCodes(await viewOf(me, rid)).length,
    plan_stops: planView.sequence.length, road_distance_m: view.plan.rider_route.road_distance_m, road_duration_s: view.plan.rider_route.road_duration_s,
    browser_wait_s: elapsed,
  }));
  await shot(rp, "live-recalculated-from-the-device-position");
  await rp.context().close();
  await admin.ctx.dispose();
});
