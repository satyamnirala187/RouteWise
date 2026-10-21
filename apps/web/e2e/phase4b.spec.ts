// Step 4B browser verification (desktop 1280 px and mobile 390 px): what the existing screens show
// once a rider's own route revision exists. The reroute itself is requested through the rider API
// (its screens and device-position capture are 4D); the origin is the rider's configured start,
// so no device position is involved. Plans use the RECORDED real local-Valhalla DU matrices.
import { expect, test } from "@playwright/test";
import { Api, ensureDepots, expectNoHorizontalOverflow, gotoRound, hold, newPage, prepareRound, signIn, P, PRIVATE_STRINGS } from "./phase2-helpers";
import { codesShown, newRound, plan, riderPage, shooter } from "./phase3-helpers";

test.afterEach(() => hold(false));

const shot = shooter("E2E_4B_SHOTS_DIR", "4b", "phase4");

test("a rider's own revision drives their cards; the admin sees it noted beside the unchanged saved plan", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "last_stop" }]);
  const routes = await plan(admin, rid);

  const { rp, external } = await riderPage(browser, "p2_asha", rid);
  const me = await Api.of(rp);
  const run = await me.ok<{ id: string }>("POST", `/api/rider/rounds/${rid}/reroute`,
    { origin: { kind: "configured_start" }, expected_plan_version: 1, expected_revision: 0 });
  let state = "queued";
  for (let i = 0; i < 200 && !["succeeded", "failed", "stale", "interrupted"].includes(state); i++) {
    state = (await me.json<{ state: string }>(`/api/rider/reroutes/${run.id}`)).state;
    if (state === "queued" || state === "running") await rp.waitForTimeout(100);
  }
  expect(state).toBe("succeeded");
  const view = await me.json<{ sequence: { orders: { order_code: string }[] }[]; plan: { rider_route: { revision: { number: number } } } }>(
    `/api/rider/rounds/${rid}/deliveries`);
  expect(view.plan.rider_route.revision.number).toBe(1);
  const revised = view.sequence.flatMap((s) => s.orders.map((o) => o.order_code));
  expect([...revised].sort()).toEqual([...routes.Asha].sort());

  await rp.getByRole("button", { name: "Refresh" }).click();
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(revised);  // the cards follow the revision
  await expect(rp.getByTestId("next-customer")).toHaveAttribute("data-order", revised[0]);
  await expect(rp.getByTestId("plan-out-of-date")).toHaveCount(0);
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 1");  // the route summary card is unchanged
  expect(external).toEqual([]);
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "01-rider-after-revision");

  const ap = await newPage(browser);
  await signIn(ap, "admin_e2e");
  await gotoRound(ap, "/admin/plan", rid);
  const asha = ap.getByTestId("plan-route").filter({ hasText: "Asha" });
  await expect(asha.getByTestId("rider-revision")).toContainText("Recalculated by the rider");
  await expect(asha.getByTestId("rider-revision")).toContainText("from their configured start");
  await expect(asha.getByTestId("rider-revision")).toContainText("The admin's plan is unchanged");   // 4D: the note now also lists the current route
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Bilal" }).getByTestId("rider-revision")).toHaveCount(0);
  await expect(ap.getByTestId("out-of-date")).toHaveCount(0);
  const html = await ap.content();
  for (const s of PRIVATE_STRINGS) expect(html).not.toContain(s);  // never a Home/Custom location
  await expectNoHorizontalOverflow(ap);
  await shot(ap, "02-admin-rider-revision");
  await ap.context().close();
  await rp.context().close();
  await admin.ctx.dispose();
});
