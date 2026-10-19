// Step 2C browser verification (desktop 1280 px and mobile 390 px). Planning uses the RECORDED
// real local-Valhalla DU matrices injected by services/api/scripts/e2e_app.py (test-only seam);
// e2e/phase2-live.spec.ts repeats a planning flow on the real local tiles when opted in.
import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  Api, P, PRIVATE_STRINGS, coords, ensureDepots, expectNoBrowserStorage, expectNoHorizontalOverflow, gotoRound, hold,
  importRound, isMobile, newPage, prepareRound, shot, shotOf, signIn, state, waitRun,
} from "./phase2-helpers";

test.afterEach(() => hold(false));

const TITLES: Record<string, string> = {
  Orders: "Orders", "Round setup": "Round setup", Plan: "Plan routes", Import: "Import orders", "Office & riders": "Office, Warehouse and riders",
};
/** Click a main-navigation link and wait until that page has rendered. */
const nav = (page: Page, name: string) => ({
  click: async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: TITLES[name], exact: true })).toBeVisible();
  },
});
const roundPicker = (page: Page) => page.getByRole("combobox", { name: "Round", exact: true });
const optimizeButton = (page: Page) => page.getByRole("button", { name: /^(Optimize routes|Planning…)$/ });
const card = (page: Page, rid: string) => page.locator(`[data-testid=destination-card][data-round="${rid}"]`);
const route = (page: Page, rider: string) => page.locator(`[data-testid=plan-route][data-rider="${rider}"]`);
const codesIn = async (loc: Locator) => (await loc.locator("[data-testid=stop-order]").allTextContents()).map((s) => s.trim());

async function orderItem(page: Page, code: string) {
  return isMobile() ? page.getByTestId("order-card").filter({ hasText: code }) : page.getByTestId("order-row").filter({ hasText: code });
}

async function chooseDestination(rp: Page, rid: string, kind: RegExp, at?: { lat: number; lng: number }) {
  const c = card(rp, rid);
  await expect(c.getByTestId("confirmation")).toBeVisible();  // loaded
  const change = c.getByRole("button", { name: "Change destination" });
  if (await change.isVisible()) await change.click();  // confirmed rounds start collapsed
  await c.getByRole("radio", { name: kind }).check();
  if (at) await c.getByLabel(/location \(latitude, longitude\)/).fill(coords(at));
  await c.getByRole("button", { name: "Save destination" }).click();
  await expect(c.getByRole("status")).toContainText("Saved");
  return c;
}

async function expectNoPrivateCoordinates(page: Page, admin: Api, rid: string) {
  const html = await page.content();
  for (const s of PRIVATE_STRINGS) expect(html).not.toContain(s);
  for (const url of [`/api/admin/rounds/${rid}/riders`, `/api/admin/rounds/${rid}/readiness`, `/api/admin/rounds/${rid}/plans`,
    `/api/admin/rounds/${rid}/planning-runs`, `/api/admin/rounds/${rid}/orders`, "/api/admin/riders", "/api/admin/depots"]) {
    const body = await (await admin.get(url)).text();
    for (const s of PRIVATE_STRINGS) expect(body, url).not.toContain(s);
  }
  const plan = await admin.get(`/api/admin/rounds/${rid}/plan`);
  if (plan.ok()) for (const s of PRIVATE_STRINGS) expect(await plan.text()).not.toContain(s);
}

test("admin sets Office and Warehouse with validation and conflict recovery, and edits a rider profile", async ({ page }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await nav(page, "Office & riders").click();
  for (const [kind, name] of [["office", "Office"], ["warehouse", "Warehouse"]] as const) {
    const box = page.getByTestId(`depot-${kind}`);
    const save = box.getByRole("button", { name: new RegExp(`^(Set|Save) ${name}$`) });
    const field = box.getByLabel("Coordinates (latitude, longitude)");
    await field.fill("next to the metro");
    await save.click();
    await expect(box.getByRole("alert")).toContainText("latitude, longitude");
    await field.fill("28.5000, 77.0000");  // valid coordinates, outside the DU North Campus area
    await save.click();
    await expect(box.getByRole("alert")).toContainText("inside the DU North Campus service area");
    await box.getByLabel("Label").fill(name);
    await field.fill(coords(P[kind]));
    await box.getByRole("button", { name: new RegExp(`^(Set|Save) ${name}$`) }).click();
    await expect(box.getByRole("status")).toContainText("Saved");
  }
  // Another admin edits the Office meanwhile: the stale form is refused, not silently overwritten.
  const office = (await admin.json<Record<string, { version: number }>>("/api/admin/depots")).office;
  await admin.ok("PUT", "/api/admin/depots/office", { version: office.version, label: "Office (edited elsewhere)", ...P.office });
  const box = page.getByTestId("depot-office");
  await box.getByLabel("Label").fill("Office main gate");
  await box.getByRole("button", { name: "Save Office" }).click();
  await expect(box.getByRole("alert")).toContainText("changed since you opened it");
  await box.getByRole("button", { name: "Reload the latest version" }).click();
  await expect(box.getByLabel("Label")).toHaveValue("Office (edited elsewhere)");
  await box.getByLabel("Label").fill("Office");
  await box.getByRole("button", { name: "Save Office" }).click();
  await expect(box.getByRole("status")).toContainText("Saved");

  const dev = page.getByTestId("rider-profile").filter({ hasText: "p2_dev" });
  await dev.getByLabel(/Display name/).fill("Dev R");
  await dev.getByRole("button", { name: /Save profile/ }).click();
  await expect(dev.getByRole("status")).toContainText("Saved");
  await dev.getByLabel(/Display name/).fill("Dev");
  await dev.getByRole("button", { name: /Save profile/ }).click();
  await expect(dev.getByRole("status")).toContainText("Saved");
  await expect(page.getByText("created and deactivated with the command-line tool")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await shot(page, "01-office-warehouse-riders");
});

test("full round: import, mixed fleet from both starts, rider confirmations, smart plan on recorded roads", async ({ page, browser }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await ensureDepots(admin);

  await nav(page, "Import").click();
  await page.getByLabel("Excel file").setInputFiles(state.phase2.workbook);
  await page.getByRole("button", { name: "Upload and preview" }).click();
  await page.getByRole("button", { name: `Save ${state.phase2.orders} orders` }).click();
  await expect(page).toHaveURL(/\/admin$/);
  const rid = (await admin.json<{ id: string; name: string }[]>("/api/admin/rounds"))[0].id;

  await nav(page, "Round setup").click();
  await roundPicker(page).selectOption(rid);
  const add = page.getByTestId("add-rider");
  for (const [rider, start] of [["Asha (p2_asha)", "Office"], ["Bilal (p2_bilal)", "Warehouse"], ["Chitra (p2_chitra)", "Warehouse"]]) {
    await add.getByLabel("Rider").selectOption({ label: rider });
    await add.getByLabel("Capacity (orders)").fill("3");
    await add.getByLabel("Start").selectOption({ label: start });
    await add.getByRole("button", { name: "Add rider" }).click();
    await expect(add.getByRole("status")).toContainText("added");
  }
  const rows = page.getByTestId("round-rider");
  await expect(rows).toHaveCount(3);
  await expect(rows.filter({ hasText: "Bilal" }).getByLabel("Vehicle for Bilal")).toHaveValue("bike");
  await expect(rows.getByTestId("confirmation")).toHaveText(["Not confirmed", "Not confirmed", "Not confirmed"]);
  await expectNoHorizontalOverflow(page);
  await shot(page, "02-round-setup-unconfirmed");

  // Gate, UI half: Optimize disabled with the riders named. API half: the server refuses too.
  await nav(page, "Plan").click();
  await expect(optimizeButton(page)).toBeDisabled();
  await expect(page.getByTestId("configuration-blockers")).toContainText("Asha has not confirmed their setup");
  await expect(page.getByTestId("optimize-why")).toContainText("finish the readiness checklist");
  await expect(page.getByTestId("limits")).toContainText("up to 80 Pending orders, 8 riders and 100 distinct");
  await shot(page, "03-plan-blocked");
  const blocked = await admin.send("POST", `/api/admin/rounds/${rid}/optimize`);
  expect(blocked.status()).toBe(409);
  expect((await blocked.json()).detail.code).toBe("NOT_READY");

  const riders: [string, RegExp, { lat: number; lng: number } | undefined][] = [
    ["p2_asha", /^Home/, P.home_r1], ["p2_bilal", /^Custom/, P.custom_r2], ["p2_chitra", /^Last stop/, undefined]];
  for (const [user, kind, at] of riders) {
    const rp = await newPage(browser);
    await signIn(rp, user);
    await gotoRound(rp, "/rider", rid);  // one round at a time since 3A
    const c = card(rp, rid);
    await expect(c.getByTestId("confirmation")).toHaveText("Not confirmed");
    await expect(c.getByTestId("setup-summary")).toContainText(user === "p2_bilal" ? "Motorbike" : "Scooter");
    await chooseDestination(rp, rid, kind, at);
    await expect(c.getByTestId("confirmation")).toHaveText("Not confirmed");  // saving is not confirming
    if (user === "p2_asha") {
      await expect(c.getByTestId("setup-summary")).toContainText(String(P.home_r1.lat));  // her own location, to her only
      await expectNoHorizontalOverflow(rp);
      await shotOf(c, "04-rider-saved-not-confirmed");
    }
    if (user === "p2_chitra") {
      // One rider still unconfirmed: still blocked, and named.
      await page.reload();
      await expect(optimizeButton(page)).toBeDisabled();
      await expect(page.getByTestId("configuration-blockers")).toContainText("Chitra has not confirmed");
      await expect(page.getByTestId("configuration-blockers")).not.toContainText("Asha");
      expect((await admin.send("POST", `/api/admin/rounds/${rid}/optimize`)).status()).toBe(409);
    }
    await c.getByRole("button", { name: "Confirm this setup" }).click();
    await expect(c.getByTestId("confirmation")).toHaveText("Confirmed");
    if (user === "p2_asha") await shotOf(c, "05-rider-confirmed");
    await expectNoBrowserStorage(rp);
    await rp.context().close();
  }

  await page.reload();
  await expect(optimizeButton(page)).toBeEnabled();
  await optimizeButton(page).click();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", "succeeded", { timeout: 60_000 });
  const view = page.getByTestId("plan-view");
  await expect(view).toHaveAttribute("data-version", "1");
  await expect(page.getByTestId("plan-route")).toHaveCount(3);
  const all = (await Promise.all(["Asha", "Bilal", "Chitra"].map((r) => codesIn(route(page, r))))).flat();
  expect(all).toHaveLength(state.phase2.orders);
  expect(new Set(all).size).toBe(state.phase2.orders);  // every order exactly once
  await expect(route(page, "Asha").getByTestId("route-start")).toHaveText("Start: Office");
  await expect(route(page, "Bilal").getByTestId("route-start")).toHaveText("Start: Warehouse");
  await expect(route(page, "Asha").getByTestId("route-end")).toHaveText("End: Home (private)");
  await expect(route(page, "Bilal").getByTestId("route-end")).toHaveText("End: Custom (private)");
  await expect(route(page, "Chitra").getByTestId("route-end")).toContainText("Last stop — the route ends at the final delivery");
  await expect(page.getByTestId("provenance")).toContainText("Recorded real-road distances");
  await expect(page.getByTestId("provenance")).toContainText("OpenStreetMap");
  await expect(view.getByText("traffic-free estimate").first()).toBeVisible();
  await expect(route(page, "Asha").getByTestId("route-distance")).toHaveText(/\d+\.\d km/);
  await expectNoPrivateCoordinates(page, admin, rid);
  await expectNoBrowserStorage(page);
  await expectNoHorizontalOverflow(page);
  await shot(page, "06-plan-smart");

  await nav(page, "Orders").click();
  await expect(page.getByTestId("assigned-badge").filter({ hasText: "Assigned: Asha" }).first()).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await shot(page, "07-orders-assigned");
});

test("equal and manual modes with owner locks, first delivery, bulk assignment and version history", async ({ page }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await ensureDepots(admin);
  const rid = await importRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 8, start: "office", kind: "office" },
    { user: "p2_dev", vehicle: "bike", capacity: 8, start: "warehouse", kind: "warehouse" },
  ]);
  const orders = await admin.json<{ id: string; order_code: string }[]>(`/api/admin/rounds/${rid}/orders`);
  const first = orders[0].order_code;

  await gotoRound(page, "/admin", rid);
  const item = await orderItem(page, first);
  await item.getByRole("button", { name: "Edit" }).click();
  const editor = page.getByTestId("order-editor");
  await expect(editor.getByTestId("assigned-rider")).toContainText("none yet");
  await editor.getByLabel("Owner lock").selectOption({ label: "Lock to Dev" });
  await editor.getByLabel("First delivery of its rider's route").check();
  await editor.getByRole("button", { name: "Save planning" }).click();
  await expect(editor.getByRole("status")).toHaveText("Planning settings saved.");
  await expect(item.getByTestId("lock-badge")).toHaveText("🔒 Locked to Dev");
  await expect(item.getByTestId("priority-badge")).toBeVisible();
  await expect(item.getByTestId("assigned-badge")).toHaveCount(0);  // a lock is not an assignment
  await shot(page, "08-order-lock-priority");

  await nav(page, "Plan").click();
  await page.getByRole("radio", { name: /^Equal/ }).check();
  await expect(page.getByRole("status").filter({ hasText: "Mode set to equal." })).toBeVisible();
  await expect(page.getByText("Not guaranteed")).toBeVisible();
  await optimizeButton(page).click();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", "succeeded", { timeout: 60_000 });
  await expect(page.getByTestId("plan-view")).toContainText("equal mode");
  const devCodes = await codesIn(route(page, "Dev"));
  expect(devCodes[0]).toBe(first);  // first delivery of the locked rider
  await shot(page, "09-plan-equal");

  await page.getByRole("radio", { name: /^Manual/ }).check();
  await expect(page.getByRole("status").filter({ hasText: "Mode set to manual." })).toBeVisible();
  await optimizeButton(page).click();
  const refusal = page.getByTestId("refusal");
  await expect(refusal).toContainText("MANUAL_ASSIGNMENT_MISSING");
  await expect(refusal).toContainText("Manual mode needs an owner lock on every Pending order");
  await expect(refusal).toContainText("the current plan (version 1) is unchanged");
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "1");
  await shot(page, "10-manual-refused");

  await nav(page, "Orders").click();
  const bulk = page.getByTestId("bulk-assign");
  await bulk.locator("summary").click();
  await bulk.getByRole("button", { name: "Select unlocked Pending" }).click();
  await bulk.getByLabel("Lock selected orders to").selectOption({ label: "Asha" });
  await bulk.getByRole("button", { name: `Apply to ${orders.length - 1} order(s)` }).click();
  await expect(bulk.getByRole("status")).toHaveText(`${orders.length - 1} order(s) locked to Asha.`);
  await expect(page.getByTestId("lock-badge").filter({ hasText: "Asha" })).toHaveCount(orders.length - 1);
  await shot(page, "11-bulk-assignment");

  await nav(page, "Plan").click();
  await optimizeButton(page).click();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", "succeeded", { timeout: 60_000 });
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "2");
  expect((await codesIn(route(page, "Asha"))).sort()).toEqual(orders.slice(1).map((o) => o.order_code).sort());
  expect(await codesIn(route(page, "Dev"))).toEqual([first]);
  await expect(page.getByTestId("ownership-changes")).toContainText("Dev → Asha");
  const history = page.getByTestId("plan-history");
  await expect(history.getByRole("listitem")).toHaveCount(2);
  await shot(page, "12-plan-manual");
  await history.getByRole("button", { name: "View version 1" }).click();
  await expect(page.getByRole("heading", { name: "History: version 1" })).toBeVisible();
  await expect(page.getByTestId("plan-view")).toContainText("Superseded");
  await expectNoHorizontalOverflow(page);
  await shot(page, "13-plan-history-version");
  await page.getByRole("button", { name: "Back to the current plan" }).click();
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "2");
});

test("capacity and first-delivery conflicts are explained and nothing is saved", async ({ page }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await ensureDepots(admin);
  const rid = await importRound(admin);
  const ids = await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 3, start: "office", kind: "office" },
    { user: "p2_bilal", vehicle: "bike", capacity: 3, start: "warehouse", kind: "last_stop" },
  ]);
  await gotoRound(page, "/admin/plan", rid);
  await optimizeButton(page).click();
  const refusal = page.getByTestId("refusal");
  await expect(refusal).toContainText("INSUFFICIENT_CAPACITY");
  await expect(refusal).toContainText("Raise riders' capacity");
  await expect(page.getByTestId("no-plan")).toBeVisible();
  expect(await admin.json(`/api/admin/rounds/${rid}/planning-runs`)).toEqual([]);
  await shot(page, "14-capacity-conflict");

  // Enough capacity, but three first deliveries for two riders.
  for (const user of ["p2_asha", "p2_bilal"]) {
    const rr = (await admin.json<{ rider_id: string; config_version: number }[]>(`/api/admin/rounds/${rid}/riders`)).find((r) => r.rider_id === ids[user])!;
    await admin.ok("PUT", `/api/admin/rounds/${rid}/riders/${ids[user]}`, { version: rr.config_version, capacity: 5 });
    const rider = await Api.login(user);
    const s = await rider.json<{ config_version: number }>(`/api/rider/rounds/${rid}`);
    await rider.ok("POST", `/api/rider/rounds/${rid}/confirm`, { config_version: s.config_version });
    await rider.ctx.dispose();
  }
  const orders = await admin.json<{ id: string; version: number }[]>(`/api/admin/rounds/${rid}/orders`);
  for (const o of orders.slice(0, 3)) await admin.ok("PUT", `/api/admin/orders/${o.id}/priority`, { version: o.version, first_priority: true });
  await page.reload();
  await optimizeButton(page).click();
  await expect(refusal).toContainText("PRIORITY_CONFLICT");
  await expect(refusal).toContainText("Each rider can have only one first delivery");
  await expect(page.getByTestId("no-plan")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await shot(page, "15-priority-conflict");
});

test("a destination change during a solve rejects the result and keeps the previous plan", async ({ page, browser }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await ensureDepots(admin);
  const rid = await importRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_chitra", vehicle: "scooter", capacity: 5, start: "warehouse", kind: "last_stop" },
  ]);
  const first = await admin.ok<{ id: string }>("POST", `/api/admin/rounds/${rid}/optimize`);
  expect((await waitRun(admin, first.id)).state).toBe("succeeded");

  await gotoRound(page, "/admin/plan", rid);
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "1");
  hold(true);
  await optimizeButton(page).click();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", /queued|running/);
  await expect(page.getByRole("heading", { name: /previous result; a new run is in progress/ })).toBeVisible();
  await expect(optimizeButton(page)).toBeDisabled();
  await shot(page, "16-run-in-progress");

  const rp = await newPage(browser);
  await signIn(rp, "p2_chitra");
  await gotoRound(rp, "/rider", rid);  // one round at a time since 3A
  const c = await chooseDestination(rp, rid, /^Warehouse/);
  await expect(c.getByTestId("confirmation")).toHaveText("Outdated — must confirm again");
  hold(false);

  const status = page.getByTestId("run-status");
  await expect(status).toHaveAttribute("data-state", "stale", { timeout: 60_000 });
  await expect(status).toContainText("Rejected — the round changed during the run");
  await expect(status).toContainText("Nothing was saved");
  await expect(status).toContainText("still version 1 from before this run");
  await expect(page.getByRole("heading", { name: "Current plan (the latest run did not replace it)" })).toBeVisible();
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "1");
  // 4B (R23): Chitra's own destination change invalidates only her route, not the whole plan.
  await expect(page.getByTestId("out-of-date")).toHaveCount(0);
  await expect(page.getByTestId("plan-route").filter({ hasText: "Chitra" }).getByTestId("rider-awaiting-recalculation")).toBeVisible();
  await expect(page.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-awaiting-recalculation")).toHaveCount(0);
  await expect(optimizeButton(page)).toBeDisabled();  // Chitra must confirm the new destination first
  expect(await admin.json<unknown[]>(`/api/admin/rounds/${rid}/plans`)).toHaveLength(1);
  await expectNoHorizontalOverflow(page);
  await shot(page, "17-run-stale");
  await rp.context().close();
});

test("a configuration change after planning marks the plan out of date; stale edits are refused", async ({ page, browser }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await ensureDepots(admin);
  const rid = await importRound(admin);
  const ids = await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "custom", at: P.custom_r2 },
  ]);
  const run = await admin.ok<{ id: string }>("POST", `/api/admin/rounds/${rid}/optimize`);
  expect((await waitRun(admin, run.id)).state).toBe("succeeded");

  await gotoRound(page, "/admin/round", rid);
  const asha = page.getByTestId("round-rider").filter({ hasText: "Asha" });
  await expect(asha.getByTestId("confirmation")).toHaveText("Confirmed");
  await expect(asha.getByTestId("destination-kind")).toHaveText("Destination: Home (private)");
  await asha.getByLabel("Capacity for Asha").fill("6");
  await asha.getByRole("button", { name: "Save setup for Asha" }).click();
  await expect(asha.getByRole("status")).toContainText("Saved");
  await expect(asha.getByTestId("confirmation")).toHaveText("Outdated — must confirm again");

  // Another admin changes Bilal meanwhile: this form is refused and can reload.
  const rr = (await admin.json<{ rider_id: string; config_version: number }[]>(`/api/admin/rounds/${rid}/riders`)).find((r) => r.rider_id === ids.p2_bilal)!;
  await admin.ok("PUT", `/api/admin/rounds/${rid}/riders/${ids.p2_bilal}`, { version: rr.config_version, capacity: 7 });
  const bilal = page.getByTestId("round-rider").filter({ hasText: "Bilal" });
  await bilal.getByLabel("Capacity for Bilal").fill("4");
  await bilal.getByRole("button", { name: "Save setup for Bilal" }).click();
  await expect(bilal.getByRole("alert")).toContainText("changed since you opened it");
  await bilal.getByRole("button", { name: "Reload the latest version" }).click();
  await expect(bilal.getByLabel("Capacity for Bilal")).toHaveValue("7");
  await expectNoPrivateCoordinates(page, admin, rid);
  await expectNoHorizontalOverflow(page);
  await shot(page, "18-round-setup-outdated");

  await nav(page, "Plan").click();
  await expect(page.getByTestId("out-of-date")).toBeVisible();
  await expect(page.getByTestId("configuration-blockers")).toContainText("Asha's setup changed after they confirmed it");
  await expect(optimizeButton(page)).toBeDisabled();
  await expect(page.getByTestId("plan-history")).toContainText("Out of date");
  await shot(page, "19-plan-out-of-date");

  const rp = await newPage(browser);
  await signIn(rp, "p2_asha");
  await gotoRound(rp, "/rider", rid);  // one round at a time since 3A
  await expect(card(rp, rid).getByTestId("confirmation-text")).toContainText("Your setup changed after you confirmed it");
  await expect(card(rp, rid).getByTestId("setup-summary")).toContainText("6 orders");
  await shotOf(card(rp, rid), "20-rider-outdated");
  await rp.context().close();
});

test("riders see only their own rounds, destinations and deliveries; Home/Custom stay private", async ({ page, browser }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.of(page);
  await ensureDepots(admin);
  const rid = await importRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "custom", at: P.custom_r2 },
  ]);
  const other = await importRound(admin);  // Asha does not take part in this one
  await prepareRound(admin, other, [{ user: "p2_bilal", vehicle: "bike", capacity: 8, start: "warehouse", kind: "custom", at: P.custom_r2 }]);
  const run = await admin.ok<{ id: string }>("POST", `/api/admin/rounds/${rid}/optimize`);
  expect((await waitRun(admin, run.id)).state).toBe("succeeded");
  const plan = await admin.json<{ routes: { rider: string; stops: { orders: { id: string; order_code: string }[] }[] }[] }>(`/api/admin/rounds/${rid}/plan`);
  const stopsOf = (name: string) => plan.routes.find((r) => r.rider === name)!.stops.flatMap((s) => s.orders);
  const mine = stopsOf("Asha"), theirs = stopsOf("Bilal");

  const rp = await newPage(browser);
  await signIn(rp, "p2_asha");
  await expect(card(rp, rid)).toBeVisible();
  await expect(card(rp, other)).toHaveCount(0);
  await expect(card(rp, rid).getByTestId("setup-summary")).toContainText(`${P.home_r1.lat}, ${P.home_r1.lng}`);
  const html = await rp.content();
  expect(html).not.toContain(String(P.custom_r2.lat));  // Bilal's Custom point never reaches Asha
  const list = rp.getByTestId("rider-order");
  for (const o of mine) await expect(list.filter({ hasText: o.order_code })).toHaveCount(1);
  for (const o of theirs) await expect(list.filter({ hasText: o.order_code })).toHaveCount(0);
  const asApi = await Api.of(rp);
  expect((await asApi.get(`/api/rider/rounds/${other}`)).status()).toBe(404);
  expect((await asApi.send("PUT", `/api/rider/rounds/${other}/destination`, { kind: "last_stop" })).status()).toBe(404);
  expect((await asApi.get(`/api/rider/orders/${theirs[0].id}`)).status()).toBe(404);
  expect((await asApi.get(`/api/admin/rounds/${rid}/riders`)).status()).toBe(403);
  expect((await asApi.send("POST", `/api/admin/rounds/${rid}/optimize`)).status()).toBe(403);
  await expectNoBrowserStorage(rp);
  await expectNoHorizontalOverflow(rp);
  await shotOf(card(rp, rid), "21-rider-own-round");
  await rp.context().close();

  for (const path of ["/admin/round", "/admin/plan", "/admin"]) {
    await gotoRound(page, path, rid);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoPrivateCoordinates(page, admin, rid);
  }
  await expectNoBrowserStorage(page);
});

test("polling stops on navigation, round switching and session expiry; stale responses never replace the selected round", async ({ page }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const a = await importRound(admin);
  const b = await importRound(admin);
  for (const rid of [a, b]) await prepareRound(admin, rid, [{ user: "p2_asha", vehicle: "scooter", capacity: 8, start: "office", kind: "office" }]);
  const done = await admin.ok<{ id: string }>("POST", `/api/admin/rounds/${b}/optimize`);
  expect((await waitRun(admin, done.id)).state).toBe("succeeded");

  const polls: { url: string; at: number }[] = [];
  page.on("request", (r) => { if (/\/api\/admin\/planning-runs\//.test(r.url())) polls.push({ url: r.url(), at: Date.now() }); });
  const pollsSince = (t: number) => polls.filter((p) => p.at > t).length;

  // A slow mode change for round A (not cancelled by switching) must not overwrite round B.
  await gotoRound(page, "/admin/plan", a);
  await expect(page.getByTestId("no-plan")).toBeVisible();
  await page.route(`**/api/admin/rounds/${a}/mode`, async (r) => {
    await new Promise((res) => setTimeout(res, 1500));
    await r.continue().catch(() => undefined);
  });
  await page.getByRole("radio", { name: /^Equal/ }).check();
  await roundPicker(page).selectOption(b);
  await page.waitForTimeout(2500);
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "1");
  await expect(page.getByRole("radio", { name: /^Smart/ })).toBeChecked();
  await expect(page.getByText("Mode set to equal.")).toHaveCount(0);
  await page.unroute(`**/api/admin/rounds/${a}/mode`);

  hold(true);
  await gotoRound(page, "/admin/plan", a);
  await optimizeButton(page).click();
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", /queued|running/);
  await expect.poll(() => polls.length, { timeout: 10_000 }).toBeGreaterThan(1);

  // Navigation away: no further polling.
  await nav(page, "Orders").click();
  await expect(page.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
  let t = Date.now();
  await page.waitForTimeout(3500);
  expect(pollsSince(t)).toBe(0);

  // Back to round A resumes; switching to round B stops A's polling and shows B's own state.
  await gotoRound(page, "/admin/plan", a);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", /queued|running/);
  await roundPicker(page).selectOption(b);
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "1");
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", "succeeded");
  t = Date.now();
  await page.waitForTimeout(3500);
  expect(pollsSince(t)).toBe(0);

  // A slow response for round A arriving after the switch to B must not replace B.
  await page.route(`**/api/admin/rounds/${a}/**`, async (r) => {
    await new Promise((res) => setTimeout(res, 1500));
    await r.continue().catch(() => undefined);  // the app may already have aborted this request
  });
  await roundPicker(page).selectOption(a);
  await roundPicker(page).selectOption(b);
  await page.waitForTimeout(2500);
  await expect(page.getByTestId("plan-view")).toHaveAttribute("data-version", "1");
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", "succeeded");
  await expect(page.getByTestId("no-plan")).toHaveCount(0);
  await expect(roundPicker(page)).toHaveValue(b);
  await page.unroute(`**/api/admin/rounds/${a}/**`);
  await shot(page, "22-round-switch");

  // Session expiry while polling: the next poll gets 401, the app returns to sign-in, polling ends.
  await roundPicker(page).selectOption(a);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-state", /queued|running/);
  const session = await Api.of(page);
  expect((await session.send("POST", "/api/auth/logout")).status()).toBe(200);
  await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 });
  t = Date.now();
  await page.waitForTimeout(3500);
  expect(pollsSince(t)).toBe(0);
  hold(false);
  const runs = await admin.json<{ id: string }[]>(`/api/admin/rounds/${a}/planning-runs`);
  expect((await waitRun(admin, runs[0].id)).state).toBe("succeeded");
  await admin.ctx.dispose();
});

/** Hold matching requests until the test calls release(); then they reach the server unchanged
 * (or get the response passed to fulfill). Deterministic "slow request" without timers. */
async function gate(page: Page, url: string) {
  let release!: (response?: { status: number; detail: string }) => void;
  const opened = new Promise<{ status: number; detail: string } | undefined>((r) => { release = r; });
  const seen: string[] = [];
  await page.route(url, async (r) => {
    seen.push(r.request().method());
    const response = await opened;
    if (response) await r.fulfill({ status: response.status, json: { detail: response.detail } }).catch(() => undefined);
    else await r.continue().catch(() => undefined);  // the app may already have aborted it
  });
  return { release, seen, done: () => page.unroute(url) };
}

test("readiness refresh shows riders' confirmations from other sessions; late responses never replace another round", async ({ page, browser }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const a = await importRound(admin);
  const b = await importRound(admin);
  await prepareRound(admin, a, [{ user: "p2_asha", vehicle: "scooter", capacity: 8, start: "office", kind: "office" }], { confirm: false });
  await prepareRound(admin, b, [
    { user: "p2_asha", vehicle: "scooter", capacity: 4, start: "office", kind: "office" },
    { user: "p2_dev", vehicle: "bike", capacity: 4, start: "warehouse", kind: "warehouse" }]);
  const readinessGets: number[] = [];
  page.on("request", (r) => { if (r.url().includes(`/api/admin/rounds/${a}/readiness`)) readinessGets.push(Date.now()); });

  await gotoRound(page, "/admin/plan", a);
  await expect(page.getByTestId("configuration-blockers")).toContainText("Asha has not confirmed");
  await expect(optimizeButton(page)).toBeDisabled();
  await expect(page.getByTestId("refresh-status")).toContainText("Readiness checked at");

  // The rider confirms in their own session; the admin page does not poll while idle.
  const rp = await newPage(browser);
  await signIn(rp, "p2_asha");
  await gotoRound(rp, "/rider", a);  // since 3A the rider page shows one round at a time (Asha is in a and b)
  await expect(card(rp, a).getByTestId("confirmation")).toHaveText("Not confirmed");
  await card(rp, a).getByRole("button", { name: "Confirm this setup" }).click();
  await expect(card(rp, a).getByTestId("confirmation")).toHaveText("Confirmed");
  await rp.context().close();
  const idleFrom = Date.now();
  await page.waitForTimeout(3000);
  expect(readinessGets.filter((t) => t > idleFrom)).toHaveLength(0);
  await expect(optimizeButton(page)).toBeDisabled();  // still the state the admin loaded

  await page.getByRole("button", { name: "Refresh readiness" }).click();
  await expect(page.getByTestId("configuration-blockers")).toHaveCount(0);
  await expect(page.getByTestId("readiness-checklist")).toContainText("1 participating rider(s), 1 confirmed");
  await expect(optimizeButton(page)).toBeEnabled();
  await expect(roundPicker(page)).toHaveValue(a);  // same round after refreshing
  await expectNoHorizontalOverflow(page);
  await shot(page, "23-readiness-refreshed");

  // Coming back to the window also refreshes: the rider changes their destination elsewhere.
  const rider = await Api.login("p2_asha");
  await rider.ok("PUT", `/api/rider/rounds/${a}/destination`, { kind: "warehouse" });
  await rider.ctx.dispose();
  await expect(optimizeButton(page)).toBeEnabled();
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByTestId("configuration-blockers")).toContainText("Asha");
  await expect(optimizeButton(page)).toBeDisabled();

  // A refresh for round A that answers late (after the switch to B) must not replace B.
  const slow = await gate(page, `**/api/admin/rounds/${a}/**`);
  await page.getByRole("button", { name: "Refresh readiness" }).click();
  await expect(page.getByTestId("refresh-status")).toContainText("Checking");
  await roundPicker(page).selectOption(b);
  await expect(page.getByTestId("readiness-checklist")).toContainText("2 participating rider(s), 2 confirmed");
  slow.release();
  await page.waitForTimeout(1500);
  await expect(roundPicker(page)).toHaveValue(b);
  await expect(page.getByTestId("readiness-checklist")).toContainText("2 participating rider(s), 2 confirmed");
  await expect(page.getByTestId("configuration-blockers")).toHaveCount(0);
  await expect(optimizeButton(page)).toBeEnabled();
  await slow.done();
  await expectNoBrowserStorage(page);
  await admin.ctx.dispose();
});

test("mode changes are saved one at a time, recover from failure and stay per round", async ({ page }) => {
  await signIn(page, "admin_e2e");
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const a = await importRound(admin);
  const b = await importRound(admin);
  for (const rid of [a, b]) await prepareRound(admin, rid, [{ user: "p2_dev", vehicle: "bike", capacity: 8, start: "warehouse", kind: "warehouse" }]);
  const radio = (name: string) => page.getByRole("radio", { name: new RegExp(`^${name}`) });
  const serverMode = async (rid: string) => (await admin.json<{ mode: string }>(`/api/admin/rounds/${rid}/readiness`)).mode;
  const expectSaving = async () => {
    for (const m of ["Smart", "Equal", "Manual"]) await expect(radio(m)).toBeDisabled();
    await expect(optimizeButton(page)).toBeDisabled();
    await expect(page.getByRole("button", { name: "Refresh readiness" })).toBeDisabled();
    await expect(page.getByTestId("optimize-why")).toContainText("the distribution mode is being saved");
    await expect(page.getByTestId("mode-status")).toHaveText("Saving the distribution mode…");
  };
  const expectIdle = async () => {
    for (const m of ["Smart", "Equal", "Manual"]) await expect(radio(m)).toBeEnabled();
    await expect(optimizeButton(page)).toBeEnabled();
    await expect(page.getByTestId("mode-status")).toHaveText("");
  };

  await gotoRound(page, "/admin/plan", a);
  await expect(radio("Smart")).toBeChecked();

  // 1. A slow save: everything that could overlap it is disabled until the server answers.
  let slow = await gate(page, `**/api/admin/rounds/${a}/mode`);
  await radio("Equal").check();
  await expect(radio("Equal")).toBeChecked();
  await expectSaving();
  await shot(page, "24-mode-saving");
  await radio("Manual").click({ force: true }).catch(() => undefined);  // a disabled radio cannot start a second save
  expect(slow.seen).toEqual(["PUT"]);
  slow.release();
  await expect(page.getByText("Mode set to equal.")).toBeVisible();
  await expectIdle();
  await expect(radio("Equal")).toBeChecked();
  expect(slow.seen).toEqual(["PUT"]);
  expect(await serverMode(a)).toBe("equal");
  await slow.done();

  // 2. A save that fails (simulated server error): the saved mode comes back, clearly reported.
  slow = await gate(page, `**/api/admin/rounds/${a}/mode`);
  await radio("Manual").check();
  await expectSaving();
  slow.release({ status: 503, detail: "Simulated server error" });
  await expect(page.getByRole("alert")).toContainText("The mode was not changed: Simulated server error.");
  await expect(radio("Equal")).toBeChecked();
  await expectIdle();
  expect(await serverMode(a)).toBe("equal");
  await shot(page, "25-mode-save-failed");
  await slow.done();

  // 3. A pending save on A leaves B usable; returning to A shows A still saving until it ends.
  slow = await gate(page, `**/api/admin/rounds/${a}/mode`);
  await radio("Manual").check();
  await expectSaving();
  await roundPicker(page).selectOption(b);
  await expect(radio("Smart")).toBeChecked();
  await expectIdle();
  await radio("Equal").check();
  await expect(page.getByText("Mode set to equal.")).toBeVisible();
  expect(await serverMode(b)).toBe("equal");
  await roundPicker(page).selectOption(a);
  await expect(radio("Manual")).toBeChecked();
  await expectSaving();
  slow.release();
  await expect(page.getByText("Mode set to manual.")).toBeVisible();
  await expect(radio("Manual")).toBeChecked();
  for (const m of ["Smart", "Equal", "Manual"]) await expect(radio(m)).toBeEnabled();
  expect(await serverMode(a)).toBe("manual");
  await slow.done();

  // 4. A's save finishing while B is shown changes nothing on B.
  slow = await gate(page, `**/api/admin/rounds/${a}/mode`);
  await radio("Smart").check();
  await roundPicker(page).selectOption(b);
  await expect(radio("Equal")).toBeChecked();
  const answered = page.waitForResponse((r) => r.url().endsWith(`/api/admin/rounds/${a}/mode`));
  slow.release();
  await answered;
  await page.waitForTimeout(1500);
  await expect(roundPicker(page)).toHaveValue(b);
  await expect(radio("Equal")).toBeChecked();
  await expectIdle();
  await expect(page.getByText("Mode set to smart.")).toHaveCount(0);
  await expect(page.getByTestId("readiness-checklist")).toBeVisible();
  await slow.done();
  await roundPicker(page).selectOption(a);
  await expect(radio("Smart")).toBeChecked();
  expect(await serverMode(a)).toBe("smart");
  await expectNoBrowserStorage(page);
  await admin.ctx.dispose();
});
