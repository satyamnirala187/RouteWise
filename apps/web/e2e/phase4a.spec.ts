// Step 4A browser verification: the next-customer panel (quick call and "Customer unavailable"),
// desktop 1280 px and mobile 390 px. Plans use the RECORDED real local-Valhalla DU matrices
// (test-only seam). Customers are synthetic; locations are public OSM points. No call is ever
// placed: a tap on Call is dispatched with the tel: navigation suppressed by the test.
import { expect, test, type Page, type Route } from "@playwright/test";
import {
  Api, P, ensureDepots, expectNoBrowserStorage, expectNoHorizontalOverflow, hold, newPage, prepareRound, signIn,
} from "./phase2-helpers";
import { edit, newRound, orderCard, ordersOf, plan, riderPage, roundPicker, shooter, telUrl } from "./phase3-helpers";

test.afterEach(() => hold(false));

// New evidence only, in its own folder; Phase 1–3 screenshots are never written by this spec.
const shot = shooter("E2E_4A_SHOTS_DIR", "4a", "phase4");
const STATUS_URL = "**/api/rider/orders/*/status";

const panel = (page: Page) => page.getByTestId("next-customer");
const unavailable = (page: Page) => panel(page).getByTestId("next-unavailable");
const serverStatus = async (admin: Api, rid: string, code: string) => (await ordersOf(admin, rid))[code].status;

async function soloRound(admin: Api, user = "p2_dev") {
  const rid = await newRound(admin);
  await prepareRound(admin, rid, [{ user, vehicle: "bike", capacity: 8, start: "warehouse", kind: "office" }]);
  const routes = await plan(admin, rid);
  return { rid, codes: routes[Object.keys(routes)[0]] };
}

/** The rider's own status change through the API (arranging state only). */
async function riderStatus(me: Api, admin: Api, rid: string, code: string, status: string) {
  const o = (await ordersOf(admin, rid))[code];
  await me.ok("POST", `/api/rider/orders/${o.id}/status`, { status, expected_version: o.version });
}

/** Hold matching requests until released; then forward them unchanged. */
async function gate(page: Page, url: string) {
  let release!: () => void;
  const opened = new Promise<void>((r) => { release = r; });
  const seen: string[] = [];
  await page.route(url, async (r: Route) => { seen.push(r.request().url()); await opened; await r.continue().catch(() => undefined); });
  return { release, seen, done: () => page.unroute(url) };
}

test("the panel shows the first saved stop's customer with the exact call target; tapping Call changes nothing", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const before = await ordersOf(admin, rid);
  const first = before[codes[0]];
  const { rp, external } = await riderPage(browser, "p2_dev", rid);

  const next = panel(rp);
  await expect(next).toHaveAttribute("data-order", codes[0]);
  await expect(next.getByTestId("next-name")).toHaveText(first.customer_name);
  await expect(next).toContainText(first.product);
  await expect(next).toContainText("Stop 1");
  await expect(next.getByTestId("next-customer-label")).toHaveText("Next");
  await expect(next.getByTestId("next-stale")).toHaveCount(0);
  const call = next.getByTestId("next-call");
  await expect(call).toHaveAttribute("href", telUrl(first.contact));
  await expect(call).toHaveAccessibleName(`Call ${first.customer_name}, next customer (${codes[0]})`);
  await expect(unavailable(rp)).toHaveAccessibleName(`Customer unavailable: postpone ${codes[0]}`);
  await expect(orderCard(rp, codes[0]).getByTestId("next-badge")).toHaveText("Next");  // same order as the cards

  // Above the route summary, which is still the 3A/3B card.
  const [p, route] = [await next.boundingBox(), await rp.getByTestId("plan-status").boundingBox()];
  expect(p!.y + p!.height).toBeLessThanOrEqual(route!.y);
  for (const id of ["plan-version", "route-ends", "route-distance"]) await expect(rp.getByTestId("plan-status").getByTestId(id)).toBeVisible();

  // A tap on Call (dialer suppressed by the test) sends nothing and changes nothing.
  const mutations: string[] = [];
  rp.on("request", (r) => { if (r.method() !== "GET" && r.url().includes("/api/")) mutations.push(`${r.method()} ${r.url()}`); });
  await rp.evaluate(() => document.addEventListener("click", (e) => {
    if ((e.target as Element | null)?.closest?.('a[href^="tel:"]')) e.preventDefault();
  }, true));
  await call.click();
  await call.focus();
  await rp.keyboard.press("Enter");
  await rp.waitForTimeout(500);
  expect(mutations).toEqual([]);
  await expect(next).toHaveAttribute("data-order", codes[0]);
  const after = await ordersOf(admin, rid);
  for (const code of codes) expect([after[code].status, after[code].version]).toEqual(["Pending", before[code].version]);
  expect(external).toEqual([]);
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "01-next-customer");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("Customer unavailable postpones only that order, and the panel moves on only after the server confirms", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const before = await ordersOf(admin, rid);
  const { rp } = await riderPage(browser, "p2_dev", rid);

  const slow = await gate(rp, STATUS_URL);
  await unavailable(rp).click();
  await expect(unavailable(rp)).toHaveText("Saving…");
  await expect(unavailable(rp)).toHaveAttribute("aria-busy", "true");
  await expect(unavailable(rp)).toBeDisabled();
  for (const code of codes.slice(0, 3)) {
    for (const b of await orderCard(rp, code).getByTestId("status-actions").getByRole("button").all()) await expect(b).toBeDisabled();
  }
  await unavailable(rp).click({ force: true }).catch(() => undefined);  // a second tap is ignored
  await expect(panel(rp)).toHaveAttribute("data-order", codes[0]);       // not before the server answers
  await expect(orderCard(rp, codes[0])).toHaveAttribute("data-status", "Pending");
  expect(slow.seen).toHaveLength(1);
  await shot(rp, "02-saving");
  slow.release();

  await expect(rp.getByRole("status").filter({ hasText: `${codes[0]} saved as Postponed.` })).toBeVisible();
  await expect(panel(rp)).toHaveAttribute("data-order", codes[1]);
  expect(slow.seen).toHaveLength(1);
  await slow.done();
  const after = await ordersOf(admin, rid);
  expect(after[codes[0]].status).toBe("Postponed");
  for (const code of codes.slice(1)) expect([after[code].status, after[code].version]).toEqual(["Pending", before[code].version]);
  await expect(orderCard(rp, codes[0])).toHaveAttribute("data-status", "Postponed");
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "03-after-unavailable");

  // Back to Pending: it is next again. Completed is never next.
  await rp.getByRole("button", { name: `Return to Pending: ${codes[0]}`, exact: true }).click();
  await expect(rp.getByRole("status").filter({ hasText: `${codes[0]} saved as Pending.` })).toBeVisible();
  await expect(panel(rp)).toHaveAttribute("data-order", codes[0]);
  await rp.getByRole("button", { name: `Mark delivered: ${codes[0]}`, exact: true }).click();
  await orderCard(rp, codes[0]).getByRole("button", { name: "Yes, delivered" }).click();
  await expect(rp.getByRole("status").filter({ hasText: `${codes[0]} saved as Completed.` })).toBeVisible();
  await expect(panel(rp)).toHaveAttribute("data-order", codes[1]);
  await rp.context().close();
  await admin.ctx.dispose();
});

test("an uncertain save keeps the same customer and retries safely; a conflict overwrites nothing", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", rid);

  // 1. The request never reaches the server.
  await rp.route(STATUS_URL, (r) => r.abort("internetdisconnected"));
  await unavailable(rp).click();
  const failed = panel(rp).getByTestId("next-failed");
  await expect(failed).toContainText("Could not confirm the save; showing the last confirmed status");
  await expect(panel(rp)).toHaveAttribute("data-order", codes[0]);
  expect(await serverStatus(admin, rid, codes[0])).toBe("Pending");
  await shot(rp, "04-uncertain");
  await rp.unroute(STATUS_URL);
  await failed.getByRole("button", { name: "Retry: mark Postponed" }).click();
  await expect(rp.getByRole("status").filter({ hasText: `${codes[0]} saved as Postponed.` })).toBeVisible();
  await expect(panel(rp)).toHaveAttribute("data-order", codes[1]);

  // 2. Saved, but the answer is lost: the panel stays; the retry is recognised as already done.
  await rp.route(STATUS_URL, async (r) => { await r.fetch(); await r.abort("connectionreset"); });
  await unavailable(rp).click();
  await expect(panel(rp).getByTestId("next-failed")).toBeVisible();
  await expect(panel(rp)).toHaveAttribute("data-order", codes[1]);
  expect(await serverStatus(admin, rid, codes[1])).toBe("Postponed");
  const version = (await ordersOf(admin, rid))[codes[1]].version;
  await rp.unroute(STATUS_URL);
  await panel(rp).getByRole("button", { name: "Retry: mark Postponed" }).click();
  await expect(rp.getByText(`${codes[1]} was already Postponed; nothing changed.`)).toBeVisible();
  expect((await ordersOf(admin, rid))[codes[1]].version).toBe(version);
  await expect(panel(rp)).toHaveAttribute("data-order", codes[2]);

  // 3. The admin completes the next order meanwhile: refused, nothing overwritten, list reloaded.
  await edit(admin, rid, codes[2], { status: "Completed" });
  await unavailable(rp).click();
  await expect(rp.getByRole("status").filter({ hasText: "Nothing was overwritten" })).toBeVisible();
  expect(await serverStatus(admin, rid, codes[2])).toBe("Completed");
  await expect(panel(rp)).toHaveAttribute("data-order", codes[3]);  // Completed is never next
  // That admin edit made the saved route out of date: the label says so.
  await expect(panel(rp).getByTestId("next-customer-label")).toHaveText("Next in saved order");
  await expect(panel(rp).getByTestId("next-stale")).toContainText("not a newly optimized route");
  await shot(rp, "05-conflict-stale");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("empty states: Postponed only, all completed, and Pending orders outside the saved route are never picked", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", rid);
  const me = await Api.of(rp);

  // Only the last order stays in a new saved route; one Postponed order is then returned to Pending
  // without a stop in that route: it is listed, but not picked as next.
  for (const code of codes.slice(0, -1)) await riderStatus(me, admin, rid, code, "Postponed");
  await plan(admin, rid);
  await riderStatus(me, admin, rid, codes.at(-1)!, "Completed");
  await riderStatus(me, admin, rid, codes[0], "Pending");
  await rp.getByRole("button", { name: "Refresh" }).click();
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 2");
  await expect(panel(rp).getByTestId("next-empty")).toContainText("None in your saved route: 1 Pending order has no place");
  await expect(panel(rp).getByTestId("next-call")).toHaveCount(0);
  await expect(panel(rp).getByTestId("next-unavailable")).toHaveCount(0);
  await expect(panel(rp)).not.toHaveAttribute("data-order", /.+/);
  await shot(rp, "06-not-in-route");

  await riderStatus(me, admin, rid, codes[0], "Postponed");
  await rp.getByRole("button", { name: "Refresh" }).click();
  await expect(panel(rp).getByTestId("next-empty")).toContainText(`No Pending customers left. ${codes.length - 1} Postponed orders stay with you`);

  for (const code of codes.slice(0, -1)) {
    await riderStatus(me, admin, rid, code, "Pending");
    await riderStatus(me, admin, rid, code, "Completed");
  }
  await rp.getByRole("button", { name: "Refresh" }).click();
  await expect(panel(rp).getByTestId("next-empty")).toHaveText("All your deliveries in this round are completed.");
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "07-all-completed");
  await rp.context().close();

  // No plan yet (Phase 1 seed: assigned, never planned): no next customer is chosen.
  const seed = await newPage(browser);
  await signIn(seed, "rider_a_e2e");
  await expect(seed.getByTestId("rider-order")).toHaveCount(2);
  await expect(panel(seed).getByTestId("next-empty")).toContainText("No route has been planned yet, so there is no next customer");
  await expect(panel(seed).getByTestId("next-call")).toHaveCount(0);
  await seed.context().close();
  await admin.ctx.dispose();
});

test("a contact that cannot be dialled gives no call link but keeps Customer unavailable", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  await edit(admin, rid, codes[0], { contact: "12345" });  // too short to dial; a text edit keeps the route current
  const { rp } = await riderPage(browser, "p2_dev", rid);
  await expect(panel(rp)).toHaveAttribute("data-order", codes[0]);
  await expect(panel(rp).getByTestId("next-call")).toHaveCount(0);
  await expect(panel(rp).getByTestId("next-call-unavailable")).toContainText("Calling unavailable: This contact does not have a dialable number of digits.");
  await expect(panel(rp).getByTestId("next-customer-label")).toHaveText("Next");
  await expect(unavailable(rp)).toBeEnabled();
  await shot(rp, "08-no-dialable-contact");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("the panel shows only the selected round's own next customer; a late answer or an ended session never changes that", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);

  // Two riders in one round: Asha's panel never shows Bilal's orders.
  const shared = await newRound(admin);
  await prepareRound(admin, shared, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "last_stop" }]);
  const routes = await plan(admin, shared);
  const asha = await riderPage(browser, "p2_asha", shared);
  await expect(panel(asha.rp)).toHaveAttribute("data-order", routes.Asha[0]);
  const html = await panel(asha.rp).innerHTML();
  for (const code of routes.Bilal) expect(html).not.toContain(code);
  await asha.rp.context().close();

  // Round switching: a late answer for the previous round never replaces the selected one.
  const a = await soloRound(admin);
  const b = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", a.rid);
  await expect(panel(rp)).toHaveAttribute("data-order", a.codes[0]);
  let release!: () => void;
  const held = new Promise<void>((r) => { release = r; });
  await rp.route(`**/api/rider/rounds/${a.rid}/deliveries`, async (r) => { await held; await r.continue().catch(() => undefined); });
  await rp.getByRole("button", { name: "Refresh" }).click();
  await roundPicker(rp).selectOption(b.rid);
  await expect(panel(rp)).toHaveAttribute("data-order", b.codes[0]);
  release();
  await rp.waitForTimeout(1000);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", b.rid);
  await expect(panel(rp)).toHaveAttribute("data-order", b.codes[0]);
  await rp.unroute(`**/api/rider/rounds/${a.rid}/deliveries`);

  // Session ended on the server: Customer unavailable returns to sign-in and changes nothing.
  const me = await Api.of(rp);
  expect((await me.send("POST", "/api/auth/logout")).status()).toBe(200);
  await unavailable(rp).click();
  await expect(rp).toHaveURL(/\/login$/, { timeout: 15_000 });
  expect(await serverStatus(admin, b.rid, b.codes[0])).toBe("Pending");
  await expect(rp.getByTestId("next-customer")).toHaveCount(0);
  await expectNoBrowserStorage(rp);
  await rp.context().close();
  await admin.ctx.dispose();
});
