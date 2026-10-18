// Step 3A browser verification: the rider's read-only delivery view (desktop 1280 px and mobile
// 390 px). Plans use the RECORDED real local-Valhalla DU matrices (test-only seam). Customers
// are synthetic; locations are public OSM points. Call and Navigate links are inspected, never
// followed: no call is placed and no external navigation is opened.
import { expect, test } from "@playwright/test";
import {
  Api, P, PRIVATE_STRINGS, ensureDepots, expectNoBrowserStorage, expectNoHorizontalOverflow, gotoRound, hold,
  newPage, prepareRound, signIn,
} from "./phase2-helpers";
import { codesShown, dirUrl, edit, newRound, orderCard, ordersOf, plan, riderPage, roundPicker, shooter, telUrl } from "./phase3-helpers";

test.afterEach(() => hold(false));

// New evidence only, in its own folder; earlier screenshots are never written by this spec.
const shot = shooter("E2E_3A_SHOTS_DIR", "3a");

test("a rider sees their own saved route in order, with customer details and safe call and navigation links", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  const ids = await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "last_stop" }]);
  const byCode = await ordersOf(admin, rid);
  const [withNotes, badContact, plusContact] = Object.values(byCode);
  await edit(admin, rid, withNotes.order_code, { instructions: "Leave with the security desk; second gate (synthetic)" });
  await edit(admin, rid, badContact.order_code, { contact: "12345" });  // stored as typed; too short to dial
  await edit(admin, rid, plusContact.order_code, { contact: "+91 00000-00042" });
  for (const o of [withNotes, badContact, plusContact]) {
    const fresh = (await ordersOf(admin, rid))[o.order_code];
    await admin.ok("PUT", `/api/admin/orders/${o.id}/lock`, { version: fresh.version, rider_id: ids.p2_asha });
  }
  const routes = await plan(admin, rid);
  const fresh = await ordersOf(admin, rid);

  const { rp, external } = await riderPage(browser, "p2_asha", rid);
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 1");
  await expect(rp.getByTestId("plan-version")).toContainText("Current");
  await expect(rp.getByTestId("plan-out-of-date")).toHaveCount(0);
  await expect(rp.getByTestId("route-ends")).toContainText("Office");
  await expect(rp.getByTestId("route-ends")).toContainText("Home (your saved location)");
  await expect(rp.getByTestId("route-distance")).toContainText("traffic-free estimate");
  await expect(rp.getByTestId("sequence")).toContainText("Google Maps chooses its own road");

  // Exactly Asha's stops, in the saved order, numbered, with the first marked Next.
  const seq = rp.getByTestId("sequence");
  expect(await codesShown(seq)).toEqual(routes.Asha);
  await expect(seq.getByTestId("stop-number")).toHaveText(routes.Asha.map((_, i) => `Stop ${i + 1}`));
  await expect(seq.getByTestId("next-badge")).toHaveCount(1);
  await expect(orderCard(rp, routes.Asha[0]).getByTestId("next-badge")).toHaveText("Next");
  for (const code of routes.Bilal) await expect(orderCard(rp, code)).toHaveCount(0);
  const html = await rp.content();
  for (const code of routes.Bilal) {
    expect(html).not.toContain(code);
    expect(html).not.toContain(fresh[code].customer_name);
  }

  for (const code of routes.Asha) {
    const o = fresh[code], c = orderCard(rp, code);
    await expect(c.getByTestId("customer")).toHaveText(o.customer_name);
    await expect(c.getByTestId("product")).toContainText(o.product);
    await expect(c.getByTestId("contact")).toHaveText(`Contact: ${o.contact}`);  // the stored string
    await expect(c).toHaveAttribute("data-status", "Pending");
    const nav = c.getByTestId("navigate-link");
    await expect(nav).toHaveAttribute("href", dirUrl(o.location.lat!, o.location.lng!));
    await expect(nav).toHaveAttribute("target", "_blank");
    await expect(nav).toHaveAttribute("rel", "noopener noreferrer");
    if (code === badContact.order_code) {
      await expect(c.getByTestId("call-link")).toHaveCount(0);
      await expect(c.getByTestId("call-unavailable")).toContainText("Calling unavailable");
      await expect(c.getByTestId("contact")).toHaveText("Contact: 12345");
    } else {
      await expect(c.getByTestId("call-link")).toHaveAttribute("href", telUrl(o.contact));
    }
  }
  await expect(orderCard(rp, plusContact.order_code).getByTestId("call-link")).toHaveAttribute("href", "tel:+910000000042");
  await expect(orderCard(rp, withNotes.order_code).getByTestId("instructions")).toHaveText(
    "Delivery instructions: Leave with the security desk; second gate (synthetic)");
  await expect(orderCard(rp, plusContact.order_code).getByTestId("instructions")).toHaveCount(0);

  // Keyboard reachable, and nothing was opened or dialled while viewing.
  const firstCall = orderCard(rp, routes.Asha.find((c) => c !== badContact.order_code)!).getByTestId("call-link");
  await firstCall.focus();
  await expect(firstCall).toBeFocused();
  await expect(firstCall).toHaveAccessibleName(/^Call P2 Customer \d+ \(/);
  expect(external).toEqual([]);
  await expectNoHorizontalOverflow(rp);
  await expectNoBrowserStorage(rp);
  await shot(rp, "01-route");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("Postponed and Completed are separate, an out-of-date plan says so, and unusable locations give no link", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  await prepareRound(admin, rid, [{ user: "p2_dev", vehicle: "bike", capacity: 8, start: "warehouse", kind: "office" }]);
  const v1 = (await plan(admin, rid)).Dev;
  const [postponed, completed, moved] = v1;
  await edit(admin, rid, postponed, { status: "Postponed" });
  await edit(admin, rid, completed, { status: "Completed" });
  const m = (await ordersOf(admin, rid))[moved];
  await admin.ok("POST", `/api/admin/orders/${m.id}/pin`, { version: m.version, lat: 28.4, lng: 77.2 });  // synthetic, south of the service area (28.55–28.83)

  const { rp, external } = await riderPage(browser, "p2_dev", rid);
  const warn = rp.getByTestId("plan-out-of-date");
  await expect(warn).toContainText("This route is out of date");
  await expect(warn).toContainText("has not been re-optimized");
  await expect(warn).toContainText("Ask your admin to optimize the round again.");
  await expect(rp.getByRole("heading", { name: /saved order \(out of date\)/ })).toBeVisible();
  const seq = rp.getByTestId("sequence");
  expect(await codesShown(seq)).toEqual(v1.slice(2));  // remaining Pending orders, saved order
  await expect(seq.getByTestId("stop-number").first()).toHaveText("Stop 3");  // original stop numbers kept
  await expect(seq.getByTestId("next-badge")).toHaveText("Next in saved order");
  expect(await codesShown(rp.getByTestId("postponed"))).toEqual([postponed]);
  expect(await codesShown(rp.getByTestId("completed"))).toEqual([completed]);
  await expect(orderCard(rp, postponed)).toHaveAttribute("data-status", "Postponed");
  await expect(orderCard(rp, postponed).getByTestId("call-link")).toHaveCount(1);
  await expect(orderCard(rp, completed).getByTestId("call-link")).toHaveCount(0);  // nothing left to do
  await expect(orderCard(rp, completed).getByTestId("navigate-link")).toHaveCount(0);
  const bad = orderCard(rp, moved);
  await expect(bad.getByTestId("navigate-link")).toHaveCount(0);
  await expect(bad.getByTestId("navigate-unavailable")).toContainText("outside the DU North Campus service area");
  expect(await rp.content()).not.toContain("28.4");
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "02-out-of-date");

  // The rider's own change: the warning says to confirm first; the planned ends are shown.
  const destination = rp.locator(`[data-testid=destination-card][data-round="${rid}"]`);
  await destination.getByRole("button", { name: "Change destination" }).click();
  await destination.getByRole("radio", { name: /^Warehouse/ }).check();
  await destination.getByRole("button", { name: "Save destination" }).click();
  await expect(warn).toContainText("Confirm your setup above, then ask your admin to optimize the round again.");
  await expect(rp.getByTestId("planned-ends")).toContainText("The saved route was planned from Warehouse to Office");
  await destination.getByRole("button", { name: "Confirm this setup" }).click();
  await expect(warn).toContainText("Ask your admin to optimize the round again.");

  // The admin fixes the pin and re-plans: version 2 replaces version 1, which is never shown.
  const m2 = (await ordersOf(admin, rid))[moved];
  await admin.ok("POST", `/api/admin/orders/${m2.id}/pin`, { version: m2.version, lat: P.gtb_nagar.lat, lng: P.gtb_nagar.lng });
  const v2 = (await plan(admin, rid)).Dev;
  await rp.getByRole("button", { name: "Refresh" }).click();
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 2");
  await expect(rp.getByTestId("plan-status")).toContainText("It replaces version 1, which is superseded and not used.");
  await expect(rp.getByTestId("plan-out-of-date")).toHaveCount(0);
  await expect(seq.getByTestId("next-badge")).toHaveText("Next");
  expect(await codesShown(seq)).toEqual(v2);
  await expect(orderCard(rp, moved).getByTestId("navigate-link")).toHaveAttribute("href", dirUrl(P.gtb_nagar.lat, P.gtb_nagar.lng));
  expect(await codesShown(rp.getByTestId("postponed"))).toEqual([postponed]);
  expect(external).toEqual([]);
  await shot(rp, "03-replanned");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("empty states: no rounds, no plan yet, and no deliveries", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const nia = await newPage(browser);
  await signIn(nia, "p3_nia");
  await expect(nia.getByTestId("no-rounds")).toContainText("You are not part of any round yet");
  await expectNoHorizontalOverflow(nia);
  await shot(nia, "04-no-rounds");
  await nia.context().close();

  const rid = await newRound(admin);
  await prepareRound(admin, rid, [{ user: "p2_chitra", vehicle: "scooter", capacity: 8, start: "office", kind: "last_stop" }], { confirm: false });
  const { rp } = await riderPage(browser, "p2_chitra", rid);
  await expect(rp.getByTestId("no-plan")).toContainText("No route has been planned for this round yet");
  await expect(rp.getByTestId("no-deliveries")).toBeVisible();
  await expect(rp.getByTestId("rider-order")).toHaveCount(0);
  await expect(rp.locator(`[data-testid=destination-card][data-round="${rid}"]`)).toBeVisible();  // 2C card kept
  await shot(rp, "05-no-plan");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("riders cannot reach another rider's round, orders or private points by changing IDs", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const shared = await newRound(admin);
  await prepareRound(admin, shared, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "custom", at: P.custom_r2 }]);
  const routes = await plan(admin, shared);
  const bilalOnly = await newRound(admin);
  await prepareRound(admin, bilalOnly, [{ user: "p2_bilal", vehicle: "bike", capacity: 8, start: "warehouse", kind: "custom", at: P.custom_r2 }]);
  const bilalOnlyCodes = (await plan(admin, bilalOnly)).Bilal;
  const all = { ...(await ordersOf(admin, shared)), ...(await ordersOf(admin, bilalOnly)) };

  const { rp } = await riderPage(browser, "p2_asha", shared);
  // A round id that is not Asha's in the URL: the page does not show it.
  await gotoRound(rp, "/rider", bilalOnly);
  await expect(rp.getByTestId("delivery-view")).toBeVisible();
  await expect(roundPicker(rp)).not.toHaveValue(bilalOnly);
  await expect(rp.getByTestId("delivery-view")).not.toHaveAttribute("data-round", bilalOnly);
  const html = await rp.content();
  for (const code of [...routes.Bilal, ...bilalOnlyCodes]) expect(html).not.toContain(code);
  // Customer names repeat across imported rounds ("P2 Customer 1…8"), so names are checked
  // within the shared round, where Bilal's customers differ from Asha's.
  for (const code of routes.Bilal) expect(html).not.toContain(`>${all[code].customer_name}<`);
  for (const s of [String(P.custom_r2.lat), String(P.custom_r2.lng)]) expect(html).not.toContain(s);

  // The server refuses, whatever the UI does.
  const me = await Api.of(rp);
  const foreign = await me.get(`/api/rider/rounds/${bilalOnly}/deliveries`);
  const missing = await me.get(`/api/rider/rounds/00000000-0000-4000-8000-000000000000/deliveries`);
  expect([foreign.status(), missing.status()]).toEqual([404, 404]);
  expect(await foreign.text()).toBe(await missing.text());
  expect((await me.get(`/api/rider/orders/${all[routes.Bilal[0]].id}`)).status()).toBe(404);
  const own = await (await me.get(`/api/rider/rounds/${shared}/deliveries`)).text();
  for (const s of PRIVATE_STRINGS) expect(own).not.toContain(s);  // no Home/Custom points in the delivery view at all
  for (const code of routes.Bilal) expect(own).not.toContain(code);
  expect((await me.get(`/api/admin/rounds/${shared}/plan`)).status()).toBe(403);
  const listed = await me.json<{ round_id: string }[]>("/api/rider/delivery-rounds");
  expect(listed.map((r) => r.round_id)).not.toContain(bilalOnly);
  await expectNoBrowserStorage(rp);
  await rp.context().close();
  await admin.ctx.dispose();
});

test("switching rounds never shows a late response for another round; session expiry returns to sign-in", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const a = await newRound(admin);
  const b = await newRound(admin);
  for (const rid of [a, b]) await prepareRound(admin, rid, [{ user: "p2_dev", vehicle: "bike", capacity: 8, start: "warehouse", kind: "warehouse" }]);
  const codesA = (await plan(admin, a)).Dev;
  const codesB = (await plan(admin, b)).Dev;

  const { rp } = await riderPage(browser, "p2_dev", a);
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(codesA);

  // Hold round A's response, switch to B, then let A's answer arrive: B stays on screen.
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  await rp.route(`**/api/rider/rounds/${a}/deliveries`, async (r) => { await gate; await r.continue().catch(() => undefined); });
  await rp.getByRole("button", { name: "Refresh" }).click();
  await roundPicker(rp).selectOption(b);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", b);
  release();
  await rp.waitForTimeout(1000);
  await expect(roundPicker(rp)).toHaveValue(b);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", b);
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(codesB);
  await rp.unroute(`**/api/rider/rounds/${a}/deliveries`);
  await expect(rp).toHaveURL(new RegExp(`round=${b}`));
  await expectNoBrowserStorage(rp);

  // Session ends on the server: the next load goes back to sign-in and shows no deliveries.
  const me = await Api.of(rp);
  expect((await me.send("POST", "/api/auth/logout")).status()).toBe(200);
  await rp.getByRole("button", { name: "Refresh" }).click();
  await expect(rp).toHaveURL(/\/login$/, { timeout: 15_000 });
  await expect(rp.getByTestId("rider-order")).toHaveCount(0);
  await rp.context().close();
  await admin.ctx.dispose();
});
