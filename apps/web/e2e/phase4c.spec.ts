// Step 4C browser verification (desktop 1280 px and mobile 390 px): the admin controls for same-building
// stops on the existing Orders page, and that the rider's existing screen still works with a shared stop.
// Chosen local default under test: only orders with EXACTLY identical pins are suggested, nothing is grouped
// until the admin confirms, nearby pins are never offered. The full rider shared-stop presentation (one
// Navigate per shared stop) is step 4D and is NOT checked here. Plans use the RECORDED real DU matrices.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Api, ensureDepots, expectNoBrowserStorage, expectNoHorizontalOverflow, gotoRound, isMobile, newPage, prepareRound, riderIds, signIn, P } from "./phase2-helpers";
import { codesShown, newRound, ordersOf, plan, riderPage, shooter, type AdminOrder } from "./phase3-helpers";

const shot = shooter("E2E_4C_SHOTS_DIR", "4c", "phase4");
// Public OpenStreetMap points (the same fixture the planner tests use); the e2e state names only a few of them.
const PT: Record<string, { lat: number; lng: number }> = Object.fromEntries(
  (JSON.parse(readFileSync(path.resolve(import.meta.dirname, "../../../tests/fixtures/public_locations_du_north.json"), "utf8")).locations as
    { id: string; lat: number; lng: number }[]).map((l) => [l.id, { lat: l.lat, lng: l.lng }]));

const byName = async (admin: Api, rid: string) => {
  const all = await ordersOf(admin, rid);
  return Object.fromEntries(Object.values(all).map((o) => [o.customer_name, o]));
};
type Named = Record<string, AdminOrder>;

async function pin(admin: Api, o: AdminOrder, lat: number, lng: number) {
  await admin.ok("POST", `/api/admin/orders/${o.id}/pin`, { version: o.version, lat, lng });
}

/** The card (phones) or table row (wider screens) of one order. */
const entry = (page: Page, code: string) =>  // matched by the order's own code cell: a badge may name another order's code
  page.locator(isMobile() ? "[data-testid=order-card]" : "[data-testid=order-row]")
    .filter({ has: page.locator(".font-mono", { hasText: new RegExp(`^${code}`) }) });

async function openPanel(page: Page) {
  const panel = page.getByTestId("stop-groups");
  await panel.locator("summary").click();
  return panel;
}

test("the admin sees identical pins suggested, groups only after confirming, and clear messages", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  let o = await byName(admin, rid);
  const [c1, c2, c3, c4, c5] = ["P2 Customer 1", "P2 Customer 2", "P2 Customer 3", "P2 Customer 4", "P2 Customer 5"];
  // Customers 1+2 share Kirori Mal's pin and 3+4 share Hindu College's; customer 5 is 10 cm from that second pin.
  await pin(admin, o[c2], PT.kirori_mal.lat, PT.kirori_mal.lng);
  await pin(admin, o[c4], PT.hindu_college.lat, PT.hindu_college.lng);
  await pin(admin, o[c5], PT.hindu_college.lat + 0.000001, PT.hindu_college.lng);
  o = await byName(admin, rid);
  const code = (name: string) => o[name].order_code;

  const page = await newPage(browser);
  const consoleErrors: string[] = [];  // React warnings (e.g. duplicate keys) show up here in the dev build
  // (the browser's own "Failed to load resource" notes for expected 401/409 answers are not application errors)
  page.on("console", (m) => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  await signIn(page, "admin_e2e");
  await gotoRound(page, "/admin", rid);
  await expect(page.getByTestId("readiness")).toBeVisible();

  const panel = await openPanel(page);
  await expect(panel).toContainText("Nothing is grouped until you confirm it");
  await expect(panel).toContainText("Nearby pins are never suggested or grouped");
  const suggestions = panel.getByTestId("group-suggestion");
  await expect(suggestions).toHaveCount(2);  // customer 5's near-identical pin is not offered
  await expect(suggestions.nth(0)).toContainText(code(c1));
  await expect(suggestions.nth(0)).toContainText(code(c2));
  await expect(suggestions.nth(1)).toContainText(code(c3));
  await expect(suggestions.nth(1)).toContainText(code(c4));
  await expect(panel).not.toContainText(code(c5));
  await expect(entry(page, code(c1)).getByTestId("same-pin-badge")).toContainText(`Same pin as ${code(c2)}`);
  await expect(entry(page, code(c5)).getByTestId("same-pin-badge")).toHaveCount(0);
  await expect(page.getByTestId("group-badge")).toHaveCount(0);  // untouched identical pins stay separate
  expect((await admin.json<{ stop_group: unknown }[]>(`/api/admin/rounds/${rid}/orders`)).every((x) => x.stop_group === null)).toBe(true);
  await expectNoHorizontalOverflow(page);
  await shot(page, "01-admin-suggestions");

  // Confirm the first suggestion.
  await suggestions.nth(0).getByRole("button", { name: "Group as one stop" }).click();
  await expect(panel.getByRole("status")).toContainText(`${code(c1)}, ${code(c2)} now share one stop`);
  await expect(panel.getByRole("status")).toContainText("Statuses, customers and riders are unchanged");
  await expect(panel.getByTestId("stop-group")).toHaveCount(1);
  await expect(suggestions).toHaveCount(1);
  await expect(entry(page, code(c1)).getByTestId("group-badge")).toContainText(`One stop with ${code(c2)}`);
  await expect(entry(page, code(c2)).getByTestId("group-badge")).toContainText(`One stop with ${code(c1)}`);
  const after = await byName(admin, rid);
  for (const n of [c1, c2]) {  // grouping touched nothing but the group
    expect(after[n].status).toBe("Pending");
    expect(after[n].customer_name).toBe(o[n].customer_name);
    expect(after[n].version).toBe(o[n].version + 1);
  }
  await shot(page, "02-admin-group-confirmed");

  // A conflict: another admin session changes a member; this page's stale copy is refused with nothing partial.
  const second = await byName(admin, rid);
  await admin.ok("PATCH", `/api/admin/orders/${second[c3].id}`, { version: second[c3].version, product: "Edited elsewhere" });
  await suggestions.nth(0).getByRole("button", { name: "Group as one stop" }).click();
  await expect(panel.getByRole("alert")).toContainText("changed since you opened them");
  await expect(panel.getByRole("alert")).toContainText("Nothing was changed");
  await expect(panel.getByRole("alert")).toContainText(code(c3));
  const listed = await admin.json<{ order_code: string; stop_group: unknown }[]>(`/api/admin/rounds/${rid}/orders`);
  expect(listed.filter((x) => [code(c3), code(c4)].includes(x.order_code)).every((x) => x.stop_group === null)).toBe(true);  // nothing partial
  await shot(page, "03-admin-conflict");
  await panel.getByRole("button", { name: "Reload the latest version" }).click();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await suggestions.nth(0).getByRole("button", { name: "Group as one stop" }).click();
  await expect(panel.getByTestId("stop-group")).toHaveCount(2);
  await expect(suggestions).toHaveCount(0);

  // A pin edit that really changes the pin takes the order out of its group, and says so.
  await entry(page, code(c2)).getByRole("button", { name: "Edit" }).click();
  const editor = page.getByTestId("order-editor");
  await editor.getByLabel("Set pin manually (latitude, longitude)").fill("28.6890, 77.2150");  // a pin no other order has
  await editor.getByRole("button", { name: "Save pin" }).click();
  await expect(editor.getByRole("status")).toContainText(`${code(c2)} left its stop group because its pin changed`);
  await expect(editor.getByRole("status")).toContainText("the group was dissolved");
  await expect(panel.getByTestId("stop-group")).toHaveCount(1);  // only customers 3+4 remain grouped
  await expect(entry(page, code(c1)).getByTestId("group-badge")).toHaveCount(0);
  await expect(entry(page, code(c2)).getByTestId("group-badge")).toHaveCount(0);
  await shot(page, "04-admin-pin-edit-notice");

  // Ungroup: a group left with one order is dissolved.
  await panel.getByRole("button", { name: `Ungroup ${code(c3)}` }).click();
  await expect(panel.getByRole("status")).toContainText(`${code(c3)} was taken out of its stop group`);
  await expect(panel.getByRole("status")).toContainText("the group was dissolved");
  await expect(panel.getByTestId("stop-group")).toHaveCount(0);
  await expect(suggestions).toHaveCount(1);  // identical pins are suggested again, never grouped on their own
  expect((await admin.json<{ stop_group: unknown }[]>(`/api/admin/rounds/${rid}/orders`)).every((x) => x.stop_group === null)).toBe(true);
  await expectNoHorizontalOverflow(page);
  await expectNoBrowserStorage(page);
  expect(consoleErrors).toEqual([]);
  await shot(page, "05-admin-ungrouped");
  await page.context().close();
  await admin.ctx.dispose();
});

test("a planned shared stop reaches the rider API as one stop with separate customers, and the rider screen still works", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  const ids = await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "last_stop" }]);
  let o = await byName(admin, rid);
  const [c1, c2] = ["P2 Customer 1", "P2 Customer 2"];
  await pin(admin, o[c2], PT.kirori_mal.lat, PT.kirori_mal.lng);
  o = await byName(admin, rid);
  for (const n of [c1, c2]) await admin.ok("PUT", `/api/admin/orders/${o[n].id}/lock`, { version: o[n].version, rider_id: (await riderIds(admin)).p2_asha });
  o = await byName(admin, rid);
  const grouped = await admin.ok<{ changed: boolean }>("POST", `/api/admin/rounds/${rid}/stop-groups`,
    { orders: [c1, c2].map((n) => ({ id: o[n].id, version: o[n].version })) });
  expect(grouped.changed).toBe(true);
  const routes = await plan(admin, rid);
  const codes = [o[c1].order_code, o[c2].order_code];
  expect(ids.p2_asha).toBeTruthy();
  expect(routes.Asha.filter((c) => codes.includes(c)).sort()).toEqual([...codes].sort());

  const { rp, external } = await riderPage(browser, "p2_asha", rid);
  const me = await Api.of(rp);
  const view = await me.json<{ sequence: { orders: { order_code: string; location: { lat: number; lng: number } | null }[]; customers: number; shared: boolean;
    location: { lat: number; lng: number } | null }[] }>(`/api/rider/rounds/${rid}/deliveries`);
  const stop = view.sequence.find((s) => s.orders.some((x) => codes.includes(x.order_code)))!;
  expect(stop.orders.map((x) => x.order_code).sort()).toEqual([...codes].sort());
  expect(stop.shared).toBe(true);
  expect(stop.customers).toBe(2);
  expect(stop.location).toEqual({ lat: PT.kirori_mal.lat, lng: PT.kirori_mal.lng });  // one validated location for the stop
  expect(stop.orders.every((x) => x.location?.lat === PT.kirori_mal.lat)).toBe(true);
  // The existing rider screen is unchanged: both customers are separate cards in the saved sequence (shared-stop
  // presentation, with one Navigate per stop, is 4D).
  await rp.getByRole("button", { name: "Refresh" }).click();
  const shown = await codesShown(rp.getByTestId("sequence"));
  expect(shown).toEqual(expect.arrayContaining(codes));
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 1");
  expect(external).toEqual([]);
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "06-rider-existing-screen-with-a-shared-stop");
  await rp.context().close();
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// Corrections after review (20 Oct 2026): honest save results, refresh after order edits, one location rule.

const UNCERTAIN = "Could not confirm the change. Reload to check the current groups.";
const FAR = { lat: 19.076, lng: 72.8777 };  // resolved, but outside the DU North Campus routing area

/** A round whose customers 1 and 2 share one pin (Kirori Mal); returns the API session, round and orders by name. */
async function roundWithIdenticalPair() {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  let o = await byName(admin, rid);
  await pin(admin, o["P2 Customer 2"], PT.kirori_mal.lat, PT.kirori_mal.lng);
  o = await byName(admin, rid);
  return { admin, rid, o };
}

async function openOrders(browser: import("@playwright/test").Browser, rid: string) {
  const page = await newPage(browser);
  await signIn(page, "admin_e2e");
  await gotoRound(page, "/admin", rid);
  await expect(page.getByTestId("readiness")).toBeVisible();
  return { page, panel: await openPanel(page) };
}

test("a grouping request the server committed but whose answer was lost is reported as uncertain; reloading shows the saved group", async ({ browser }) => {
  const { admin, rid, o } = await roundWithIdenticalPair();
  const [c1, c2] = [o["P2 Customer 1"], o["P2 Customer 2"]];
  const { page, panel } = await openOrders(browser, rid);
  let posts = 0;
  await page.route(`**/api/admin/rounds/${rid}/stop-groups`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts += 1;
    await route.fetch();                       // the server receives the request and commits it …
    await route.abort("connectionreset");      // … but the answer never reaches the page
  });
  await panel.getByTestId("group-suggestion").getByRole("button", { name: "Group as one stop" }).click();
  await expect(panel.getByRole("status")).toContainText(UNCERTAIN);
  await expect(panel).not.toContainText("Nothing was changed");  // the server HAS changed it: never claim otherwise
  await expect(panel.getByTestId("stop-group")).toHaveCount(0);   // this page does not know yet
  const server = await admin.json<{ order_code: string; stop_group: unknown }[]>(`/api/admin/rounds/${rid}/orders`);
  expect(server.filter((x) => [c1.order_code, c2.order_code].includes(x.order_code)).every((x) => x.stop_group !== null)).toBe(true);
  await page.waitForTimeout(800);
  expect(posts).toBe(1);                       // no automatic retry
  await shot(page, "07-admin-uncertain-save");
  await panel.getByRole("button", { name: "Reload the current groups" }).click();
  await expect(panel.getByTestId("stop-group")).toHaveCount(1);  // the reload fetched the server's data
  await expect(panel.getByTestId("stop-group")).toContainText(`${c1.order_code}, ${c2.order_code}`);
  await expect(panel.getByTestId("group-suggestion")).toHaveCount(0);
  await expect(panel.getByRole("status")).toContainText("Reloaded");
  await expect(entry(page, c1.order_code).getByTestId("group-badge")).toBeVisible();
  expect(posts).toBe(1);
  await page.context().close();
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// Correction after the second review (20 Oct 2026): the reload offered after an uncertain outcome confirms only
// after the current round's data has really loaded.

/** The server commits the grouping, the answer is lost: the panel is in its "uncertain" state. Returns the POST count. */
async function loseTheGroupingAnswer(page: Page, panel: ReturnType<Page["getByTestId"]>, rid: string) {
  const count = { posts: 0 };
  await page.route(`**/api/admin/rounds/${rid}/stop-groups`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    count.posts += 1;
    await route.fetch();
    await route.abort("connectionreset");
  });
  await panel.getByTestId("group-suggestion").getByRole("button", { name: "Group as one stop" }).click();
  await expect(panel.getByRole("status")).toContainText(UNCERTAIN);
  return count;
}

test("a delayed reload shows a loading state, and only a finished load confirms it", async ({ browser }) => {
  const { admin, rid, o } = await roundWithIdenticalPair();
  const [c1, c2] = [o["P2 Customer 1"], o["P2 Customer 2"]];
  const { page, panel } = await openOrders(browser, rid);
  const sent = await loseTheGroupingAnswer(page, panel, rid);
  let hold = false, reached = false;
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(`**/api/admin/rounds/${rid}/orders`, async (route) => {
    if (hold) { reached = true; await gate; }
    await route.continue();
  });
  hold = true;
  await panel.getByRole("button", { name: "Reload the current groups" }).click();
  await expect.poll(() => reached).toBe(true);                       // the reload is in flight and held
  await expect(panel.getByTestId("groups-reloading")).toContainText("Reloading the current groups");
  await expect(panel).not.toContainText("Reloaded:");                // nothing is confirmed yet …
  await expect(panel).not.toContainText(UNCERTAIN);
  await expect(panel.getByRole("button", { name: "Reload the current groups" })).toHaveCount(0);
  await expect(panel.getByTestId("group-suggestion").getByRole("button", { name: "Group as one stop" })).toBeDisabled();
  await shot(page, "10-admin-reload-loading");
  await page.waitForTimeout(500);
  await expect(panel.getByTestId("groups-reloading")).toBeVisible();  // … however long it takes
  release();
  await expect(panel.getByRole("status")).toContainText("Reloaded: these are the groups the server has now.");
  await expect(panel.getByTestId("groups-reloading")).toHaveCount(0);
  await expect(panel.getByTestId("stop-group")).toContainText(`${c1.order_code}, ${c2.order_code}`);
  expect(sent.posts).toBe(1);                                        // the change was never sent again
  await page.context().close();
  await admin.ctx.dispose();
});

test("a failed reload keeps the uncertain warning and allows another read-only reload", async ({ browser }) => {
  const { admin, rid, o } = await roundWithIdenticalPair();
  const [c1, c2] = [o["P2 Customer 1"], o["P2 Customer 2"]];
  const { page, panel } = await openOrders(browser, rid);
  const sent = await loseTheGroupingAnswer(page, panel, rid);
  let reads = 0;
  const failures: ((route: import("@playwright/test").Route) => Promise<void>)[] = [
    (r) => r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Internal Server Error" }) }),
    (r) => r.abort("connectionreset"),
  ];
  await page.route(`**/api/admin/rounds/${rid}/stop-groups`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();   // the lost-answer handler deals with the POST
    if (reads < failures.length) return failures[reads++](route);
    await route.continue();                                            // from the third read on, the server answers
  });
  const reload = panel.getByRole("button", { name: "Reload the current groups" });
  for (let i = 0; i < failures.length; i++) {
    await reload.click();
    await expect.poll(() => reads).toBe(i + 1);
    await expect(panel.getByRole("status")).toContainText(UNCERTAIN);    // the warning is back, not a success
    await expect(panel).not.toContainText("Reloaded:");
    await expect(panel.getByTestId("groups-reloading")).toHaveCount(0);
    await expect(reload).toBeVisible();                                   // and the read can be tried again
    await expect(panel.getByTestId("stop-group")).toHaveCount(0);        // the panel does not claim to know the groups
  }
  await shot(page, "11-admin-reload-failed-retry-available");
  await reload.click();                                                   // third read succeeds
  await expect(panel.getByRole("status")).toContainText("Reloaded: these are the groups the server has now.");
  await expect(panel.getByTestId("stop-group")).toContainText(`${c1.order_code}, ${c2.order_code}`);
  await expect(reload).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);                   // the failed reads' page error is gone too
  expect(sent.posts).toBe(1);                                             // no read failure ever re-sent the change
  const server = await admin.json<{ stop_group: unknown }[]>(`/api/admin/rounds/${rid}/orders`);
  expect(server.filter((x) => x.stop_group !== null)).toHaveLength(2);    // one group, committed once
  await page.context().close();
  await admin.ctx.dispose();
});

test("a reload overtaken by a newer refresh of the same round is confirmed by what that newer refresh loaded", async ({ browser }) => {
  const { admin, rid, o } = await roundWithIdenticalPair();
  const [c1, c2] = [o["P2 Customer 1"], o["P2 Customer 2"]];
  const { page, panel } = await openOrders(browser, rid);
  await loseTheGroupingAnswer(page, panel, rid);
  let held = false;
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(`**/api/admin/rounds/${rid}/orders`, async (route) => {
    if (!held) { held = true; await gate; }       // only the reload's own read is held; later reads pass
    await route.continue();
  });
  await panel.getByRole("button", { name: "Reload the current groups" }).click();
  await expect.poll(() => held).toBe(true);
  // A saved edit of an order outside the group (this page still holds the group members' old versions) starts a newer refresh.
  await entry(page, o["P2 Customer 3"].order_code).getByRole("button", { name: "Edit" }).click();
  const editor = page.getByTestId("order-editor");
  await editor.getByLabel("Product").fill("Edited while reloading");
  await editor.getByRole("button", { name: "Save details" }).click();
  await expect(editor.getByRole("status")).toContainText("Saved.");
  await expect(panel.getByTestId("stop-group")).toContainText(`${c1.order_code}, ${c2.order_code}`);  // the newer data is on screen
  await expect(panel.getByTestId("groups-reloading")).toBeVisible();                                  // the older read has not returned
  release();
  await expect(panel.getByRole("status")).toContainText("Reloaded: these are the groups the server has now.");
  await expect(panel.getByTestId("groups-reloading")).toHaveCount(0);
  await expect(panel.getByTestId("stop-group")).toHaveCount(1);
  await page.context().close();
  await admin.ctx.dispose();
});

test("a reload still loading when another round is selected never confirms or replaces the new round", async ({ browser }) => {
  const { admin, rid: ridA, o: a } = await roundWithIdenticalPair();
  const ridB = await newRound(admin);
  const b = await byName(admin, ridB);
  const { page, panel } = await openOrders(browser, ridA);
  await loseTheGroupingAnswer(page, panel, ridA);
  let hold = false, reached = false;
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(`**/api/admin/rounds/${ridA}/orders`, async (route) => {
    if (hold) { reached = true; await gate; }
    await route.continue();
  });
  hold = true;
  await panel.getByRole("button", { name: "Reload the current groups" }).click();
  await expect.poll(() => reached).toBe(true);
  await page.getByRole("combobox", { name: "Round", exact: true }).selectOption(ridB);
  await expect(entry(page, b["P2 Customer 1"].order_code)).toBeVisible();
  release();                                                              // round A's reload finishes late
  await page.waitForTimeout(800);
  await expect(entry(page, b["P2 Customer 1"].order_code)).toBeVisible();
  await expect(entry(page, a["P2 Customer 1"].order_code)).toHaveCount(0);
  await expect(page.getByText("Reloaded:")).toHaveCount(0);              // round A's confirmation is not shown on round B
  await expect(page.getByTestId("groups-reloading")).toHaveCount(0);
  await expect(page.getByTestId("stop-group")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Round", exact: true })).toHaveValue(ridB);
  await page.context().close();
  await admin.ctx.dispose();
});

test("server errors, unreadable answers and lost answers are never reported as 'nothing was changed'", async ({ browser }) => {
  const { admin, rid, o } = await roundWithIdenticalPair();
  const { page, panel } = await openOrders(browser, rid);
  const group = () => panel.getByTestId("group-suggestion").getByRole("button", { name: "Group as one stop" }).click();
  let attempts = 0;
  const answers: ((route: import("@playwright/test").Route) => Promise<void>)[] = [
    (r) => r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Internal Server Error" }) }),
    (r) => r.fulfill({ status: 200, contentType: "text/html", body: "<html>Bad gateway page</html>" }),
    (r) => r.abort("connectionreset"),
  ];
  await page.route(`**/api/admin/rounds/${rid}/stop-groups`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await answers[attempts++](route);
  });
  for (let i = 0; i < answers.length; i++) {
    await group();
    await expect(panel.getByRole("status")).toContainText(UNCERTAIN);
    await expect(panel).not.toContainText("Nothing was changed");
    await expect(panel.getByRole("button", { name: "Reload the current groups" })).toBeVisible();
    expect(attempts).toBe(i + 1);              // one request per click; nothing was retried by the page
  }
  // An answer the API itself wrote keeps the definite wording: it said no, so nothing was changed.
  await page.unroute(`**/api/admin/rounds/${rid}/stop-groups`);
  const stale = await byName(admin, rid);
  await admin.ok("PATCH", `/api/admin/orders/${stale["P2 Customer 1"].id}`, { version: stale["P2 Customer 1"].version, product: "Edited elsewhere" });
  await group();
  await expect(panel.getByRole("alert")).toContainText("Nothing was changed");
  await expect(panel.getByRole("button", { name: "Reload the latest version" })).toBeVisible();
  expect(o["P2 Customer 1"].order_code).toBeTruthy();
  await page.context().close();
  await admin.ctx.dispose();
});

test("pin edits create and remove same-pin suggestions without switching rounds", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  const o = await byName(admin, rid);
  const [c1, c2] = [o["P2 Customer 1"].order_code, o["P2 Customer 2"].order_code];
  const { page, panel } = await openOrders(browser, rid);
  await expect(panel.getByTestId("no-stop-groups")).toBeVisible();
  const setPin = async (coords: string) => {
    const editor = page.getByTestId("order-editor");
    await editor.getByLabel("Set pin manually (latitude, longitude)").fill(coords);
    await editor.getByRole("button", { name: "Save pin" }).click();
    await expect(editor.getByRole("status")).toContainText("Pin saved.");  // the editor's own confirmation stays
  };
  await entry(page, c2).getByRole("button", { name: "Edit" }).click();
  await setPin(`${PT.kirori_mal.lat}, ${PT.kirori_mal.lng}`);              // now identical to customer 1
  await expect(panel.getByTestId("group-suggestion")).toHaveCount(1);
  await expect(panel.getByTestId("group-suggestion")).toContainText(`${c1} (Pending), ${c2} (Pending)`);
  await expect(entry(page, c1).getByTestId("same-pin-badge")).toContainText(`Same pin as ${c2}`);
  await expect(entry(page, c2).getByTestId("same-pin-badge")).toContainText(`Same pin as ${c1}`);
  await expect(panel.getByTestId("no-stop-groups")).toHaveCount(0);
  await shot(page, "08-admin-pin-edit-creates-suggestion");
  await setPin("28.6890, 77.2150");                                          // a pin no other order has
  await expect(panel.getByTestId("group-suggestion")).toHaveCount(0);
  await expect(page.getByTestId("same-pin-badge")).toHaveCount(0);
  await expect(panel.getByTestId("no-stop-groups")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`round=${rid}`));                  // the whole time, the same round
  await page.context().close();
  await admin.ctx.dispose();
});

test("a normal order edit followed by grouping uses fresh versions and succeeds", async ({ browser }) => {
  const { admin, rid, o } = await roundWithIdenticalPair();
  const [c1, c2] = [o["P2 Customer 1"], o["P2 Customer 2"]];
  const { page, panel } = await openOrders(browser, rid);
  await expect(panel.getByTestId("group-suggestion")).toHaveCount(1);
  await entry(page, c1.order_code).getByRole("button", { name: "Edit" }).click();  // bumps customer 1's version
  const editor = page.getByTestId("order-editor");
  await editor.getByLabel("Product").fill("Edited product");
  await editor.getByRole("button", { name: "Save details" }).click();
  await expect(editor.getByRole("status")).toContainText("Saved.");
  await panel.getByTestId("group-suggestion").getByRole("button", { name: "Group as one stop" }).click();
  await expect(panel.getByRole("status")).toContainText(`${c1.order_code}, ${c2.order_code} now share one stop`);
  await expect(panel.getByRole("alert")).toHaveCount(0);                      // no stale-version conflict
  const after = await byName(admin, rid);
  expect(after["P2 Customer 1"].version).toBe(c1.version + 2);               // the edit, then the grouping
  expect(after["P2 Customer 1"].product).toBe("Edited product");
  await page.context().close();
  await admin.ctx.dispose();
});

test("two identical out-of-area pins get neither a suggestion nor a same-pin badge", async ({ browser }) => {
  const { admin, rid, o } = await roundWithIdenticalPair();
  for (const n of ["P2 Customer 7", "P2 Customer 8"]) await pin(admin, o[n], FAR.lat, FAR.lng);
  const { page, panel } = await openOrders(browser, rid);
  await expect(panel.getByTestId("group-suggestion")).toHaveCount(1);          // only the valid pair
  await expect(panel.getByTestId("group-suggestion")).toContainText(o["P2 Customer 1"].order_code);
  await expect(panel).not.toContainText(o["P2 Customer 7"].order_code);
  await expect(panel).not.toContainText(o["P2 Customer 8"].order_code);
  await expect(entry(page, o["P2 Customer 1"].order_code).getByTestId("same-pin-badge")).toBeVisible();
  await expect(entry(page, o["P2 Customer 7"].order_code).getByTestId("same-pin-badge")).toHaveCount(0);
  await expect(entry(page, o["P2 Customer 8"].order_code).getByTestId("same-pin-badge")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await shot(page, "09-admin-out-of-area-identical-pins");
  await page.context().close();
  await admin.ctx.dispose();
});

for (const trigger of ["a saved order edit", "a group action"] as const) {
  test(`a delayed refresh of the previous round never replaces the selected round (${trigger})`, async ({ browser }) => {
    const { admin, rid: ridA, o: a } = await roundWithIdenticalPair();
    const ridB = await newRound(admin);
    const b = await byName(admin, ridB);
    const codeA = a["P2 Customer 1"].order_code;
    const codeB = b["P2 Customer 1"].order_code;
    expect(codeA).not.toBe(codeB);
    const { page, panel } = await openOrders(browser, ridA);
    await expect(entry(page, codeA)).toBeVisible();
    let hold = false, reached = false;
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    await page.route(`**/api/admin/rounds/${ridA}/orders`, async (route) => {
      if (hold) { reached = true; await gate; }   // the answer for round A arrives late
      await route.continue();
    });
    hold = true;
    if (trigger === "a saved order edit") {
      await entry(page, codeA).getByRole("button", { name: "Edit" }).click();
      const editor = page.getByTestId("order-editor");
      await editor.getByLabel("Product").fill("Edited in round A");
      await editor.getByRole("button", { name: "Save details" }).click();
      await expect(editor.getByRole("status")).toContainText("Saved.");
    } else {
      await panel.getByTestId("group-suggestion").getByRole("button", { name: "Group as one stop" }).click();
      await expect(panel.getByRole("status")).toContainText("now share one stop");
    }
    await expect.poll(() => reached).toBe(true);   // round A's reload is in flight and held
    await page.getByRole("combobox", { name: "Round", exact: true }).selectOption(ridB);
    await expect(entry(page, codeB)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`round=${ridB}`));
    release();                                     // now the old answer arrives
    await page.waitForTimeout(800);
    await expect(entry(page, codeB)).toBeVisible();
    await expect(entry(page, codeA)).toHaveCount(0);
    await expect(page.getByTestId("group-badge")).toHaveCount(0);   // round A's group (if any) is not shown on round B
    await expect(panel.getByTestId("stop-group")).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "Round", exact: true })).toHaveValue(ridB);
    await page.context().close();
    await admin.ctx.dispose();
  });
}
