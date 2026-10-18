// Opt-in: the planning flow against the REAL local Valhalla tiles (no recorded matrices).
//   ROUTEWISE_E2E_LIVE=1 E2E_SHOTS_DIR=<scratch> scripts/e2e.sh e2e/phase2-live.spec.ts
// Needs spikes/valhalla/data/valhalla_tiles. Customers are synthetic; points are public OSM points.
import { expect, test } from "@playwright/test";
import { Api, P, ensureDepots, gotoRound, importRound, newPage, prepareRound, shot, signIn, state } from "./phase2-helpers";

test.skip(process.env.ROUTEWISE_E2E_LIVE !== "1", "set ROUTEWISE_E2E_LIVE=1 to plan on the real local Valhalla tiles");

test("live: a mixed-fleet round planned in the browser on real local Valhalla roads", async ({ page, browser }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await ensureDepots(admin);
  const rid = await importRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 4, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 4, start: "warehouse", kind: "custom", at: P.custom_r2 },
  ], { confirm: true });
  // The third rider confirms in the browser, as in the recorded suite.
  const ids = await prepareRound(admin, rid, [{ user: "p2_chitra", vehicle: "scooter", capacity: 4, start: "warehouse", kind: "last_stop" }], { confirm: false });
  expect(ids.p2_chitra).toBeTruthy();
  const rp = await newPage(browser);
  await signIn(rp, "p2_chitra");
  const card = rp.locator(`[data-testid=destination-card][data-round="${rid}"]`);
  await card.getByRole("button", { name: "Confirm this setup" }).click();
  await expect(card.getByTestId("confirmation")).toHaveText("Confirmed");
  await rp.context().close();

  await gotoRound(page, "/admin/plan", rid);
  const started = Date.now();
  await page.getByRole("button", { name: "Optimize routes" }).click();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", "succeeded", { timeout: 180_000 });
  const elapsed = (Date.now() - started) / 1000;
  const provenance = page.getByTestId("provenance");
  await expect(provenance).toContainText("Live road distances from local Valhalla (OpenStreetMap data)");
  await expect(provenance).not.toContainText("Recorded");
  await expect(provenance).not.toContainText("recorded response");
  const codes = (await page.locator("[data-testid=stop-order]").allTextContents()).map((s) => s.trim());
  expect(new Set(codes).size).toBe(state.phase2.orders);
  expect(codes).toHaveLength(state.phase2.orders);

  const plan = await admin.json<{ version: number; provenance: Record<string, unknown>; summary: { total_road_distance_m: number }; routes: { profile: string }[] }>(`/api/admin/rounds/${rid}/plan`);
  expect(plan.provenance.real_road).toBe(true);
  expect(plan.provenance.recorded).toBe(false);
  expect(new Set(plan.routes.map((r) => r.profile))).toEqual(new Set(["motor_scooter", "motorcycle"]));
  const run = (await admin.json<{ timings: Record<string, number> }[]>(`/api/admin/rounds/${rid}/planning-runs`))[0];
  console.log("LIVE-BROWSER", JSON.stringify({
    project: test.info().project.name, provider: plan.provenance.provider, real_road: plan.provenance.real_road,
    recorded: plan.provenance.recorded, profiles: [...new Set(plan.routes.map((r) => r.profile))].sort(),
    total_road_distance_m: plan.summary.total_road_distance_m, timings: run.timings, browser_wait_s: elapsed,
  }));
  await shot(page, "live-plan");
});
