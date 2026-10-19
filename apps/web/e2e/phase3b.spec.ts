// Step 3B browser verification: a rider's own delivery-status updates (desktop 1280 px and mobile
// 390 px). Plans use the RECORDED real local-Valhalla DU matrices (test-only seam). Customers are
// synthetic; locations are public OSM points. Slow and failed requests are produced with
// page.route; no call or navigation is ever opened.
import { expect, test, type Page, type Route } from "@playwright/test";
import {
  Api, ensureDepots, expectNoBrowserStorage, expectNoHorizontalOverflow, gotoRound, hold, newPage, prepareRound, signIn,
} from "./phase2-helpers";
import { codesShown, edit, newRound, orderCard, ordersOf, plan, riderPage, roundPicker, shooter } from "./phase3-helpers";

test.afterEach(() => hold(false));

const shot = shooter("E2E_3B_SHOTS_DIR", "3b");
const STATUS_URL = "**/api/rider/orders/*/status";

async function soloRound(admin: Api, user = "p2_dev") {
  const rid = await newRound(admin);
  await prepareRound(admin, rid, [{ user, vehicle: "bike", capacity: 8, start: "warehouse", kind: "office" }]);
  const routes = await plan(admin, rid);
  return { rid, codes: routes[Object.keys(routes)[0]] };
}

const action = (page: Page, label: string, code: string) => page.getByRole("button", { name: `${label}: ${code}`, exact: true });
const sectionCount = (page: Page, testId: string) => page.getByTestId(testId).getByRole("heading").locator("span");
const serverStatus = async (admin: Api, rid: string, code: string) => (await ordersOf(admin, rid))[code].status;

/** Hold matching requests until released; then forward them unchanged. */
async function gate(page: Page, url: string) {
  let release!: () => void;
  const opened = new Promise<void>((r) => { release = r; });
  const seen: string[] = [];
  await page.route(url, async (r: Route) => { seen.push(r.request().url()); await opened; await r.continue().catch(() => undefined); });
  return { release, seen, done: () => page.unroute(url) };
}

test("a rider postpones, returns to Pending and completes their own orders; sections, counts and next stop follow", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const [a, b] = codes;
  const { rp, external } = await riderPage(browser, "p2_dev", rid);
  const seq = rp.getByTestId("sequence");
  await expect(orderCard(rp, a).getByTestId("next-badge")).toHaveText("Next");
  await expect(sectionCount(rp, "sequence")).toHaveText(`(${codes.length})`);
  await expect(roundPicker(rp).locator("option:checked")).toContainText(`${codes.length} to deliver`);
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "01-actions");

  // Postpone the next stop: it leaves the route; the next Pending stop becomes Next.
  await action(rp, "Postpone", a).click();
  await expect(rp.getByRole("status").filter({ hasText: `${a} saved as Postponed.` })).toBeVisible();
  expect(await codesShown(rp.getByTestId("postponed"))).toEqual([a]);
  expect(await codesShown(seq)).toEqual(codes.slice(1));
  await expect(orderCard(rp, b).getByTestId("next-badge")).toHaveText("Next");
  await expect(sectionCount(rp, "sequence")).toHaveText(`(${codes.length - 1})`);
  await expect(roundPicker(rp).locator("option:checked")).toContainText(`${codes.length - 1} to deliver`);
  await expect(orderCard(rp, a)).toHaveAttribute("data-status", "Postponed");
  await expect(orderCard(rp, a).getByTestId("call-link")).toHaveCount(1);  // still reachable while Postponed

  // Mark the new next stop delivered: a second, explicit tap is required.
  await action(rp, "Mark delivered", b).click();
  await expect(orderCard(rp, b).getByTestId("confirm-delivered")).toContainText("You cannot undo this yourself");
  await expect(orderCard(rp, b)).toHaveAttribute("data-status", "Pending");  // nothing saved yet
  await shot(rp, "02-confirm-delivered");
  await orderCard(rp, b).getByRole("button", { name: "Yes, delivered" }).click();
  await expect(rp.getByRole("status").filter({ hasText: `${b} saved as Completed.` })).toBeVisible();
  expect(await codesShown(rp.getByTestId("completed"))).toEqual([b]);
  const done = orderCard(rp, b);
  for (const id of ["call-link", "navigate-link", "status-actions"]) await expect(done.getByTestId(id)).toHaveCount(0);
  await expect(done.getByRole("button")).toHaveCount(0);
  await shot(rp, "02b-all-statuses");  // Pending, Postponed and Completed cards together

  // Explicit return to Pending: it goes back to its saved stop (it had one in this plan).
  await action(rp, "Return to Pending", a).click();
  await expect(rp.getByRole("status").filter({ hasText: `${a} saved as Pending.` })).toBeVisible();
  expect(await codesShown(seq)).toEqual(codes.filter((c) => c !== b));
  await expect(orderCard(rp, a).getByTestId("stop-number")).toHaveText("Stop 1");
  await expect(orderCard(rp, a).getByTestId("next-badge")).toHaveText("Next");
  await expect(rp.getByTestId("postponed")).toHaveCount(0);

  // Ordinary progress keeps the saved route usable and says so; totals stay "planned".
  await expect(rp.getByTestId("plan-out-of-date")).toHaveCount(0);
  await expect(rp.getByTestId("progress-since-plan")).toContainText("The remaining stops keep their saved order");
  await expect(rp.getByTestId("route-distance")).toContainText("This is the plan, not the distance left");
  expect([await serverStatus(admin, rid, a), await serverStatus(admin, rid, b)]).toEqual(["Pending", "Completed"]);
  expect(external).toEqual([]);
  await expectNoBrowserStorage(rp);
  await shot(rp, "03-after-progress");
  await rp.context().close();

  const ap = await newPage(browser);
  await signIn(ap, "admin_e2e");
  await gotoRound(ap, "/admin/plan", rid);
  await expect(ap.getByTestId("progress-since-plan")).toBeVisible();
  await expect(ap.getByTestId("out-of-date")).toHaveCount(0);
  await expect(ap.getByTestId("plan-view")).toContainText("Planned total road distance");
  await expect(ap.getByTestId("plan-history")).toContainText("Deliveries updated");
  await shot(ap, "04-admin-progress");
  await ap.context().close();
  await admin.ctx.dispose();
});

test("while a save is in flight every status action waits, and success appears only after the server confirms", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", rid);
  const slow = await gate(rp, STATUS_URL);
  await action(rp, "Postpone", codes[0]).click();
  const busy = orderCard(rp, codes[0]).getByRole("button", { name: `Postpone: ${codes[0]}` });
  await expect(busy).toHaveText("Saving…");
  await expect(busy).toHaveAttribute("aria-busy", "true");
  for (const code of codes.slice(0, 3)) {
    for (const b of await orderCard(rp, code).getByTestId("status-actions").getByRole("button").all()) await expect(b).toBeDisabled();
  }
  await busy.click({ force: true }).catch(() => undefined);  // a second tap is ignored
  await action(rp, "Postpone", codes[1]).click({ force: true }).catch(() => undefined);
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(codes);  // not moved before the server answers
  await expect(rp.getByText(`${codes[0]} saved as Postponed.`)).toHaveCount(0);
  expect(slow.seen).toHaveLength(1);
  await shot(rp, "05-saving");
  slow.release();
  await expect(rp.getByText(`${codes[0]} saved as Postponed.`)).toBeVisible();
  expect(slow.seen).toHaveLength(1);
  expect(await codesShown(rp.getByTestId("postponed"))).toEqual([codes[0]]);
  expect(await serverStatus(admin, rid, codes[1])).toBe("Pending");
  await slow.done();
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a conflicting change elsewhere is reloaded and explained; nothing is overwritten", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", rid);
  await edit(admin, rid, codes[0], { status: "Completed" });  // the admin completes it meanwhile
  await action(rp, "Postpone", codes[0]).click();
  await expect(rp.getByRole("status").filter({ hasText: "Nothing was overwritten" })).toBeVisible();
  await expect(orderCard(rp, codes[0])).toHaveAttribute("data-status", "Completed");
  await expect(orderCard(rp, codes[0]).getByRole("button")).toHaveCount(0);
  expect(await serverStatus(admin, rid, codes[0])).toBe("Completed");
  // That admin edit is a genuine change: the saved route is reported out of date.
  await expect(rp.getByTestId("plan-out-of-date")).toBeVisible();
  await shot(rp, "06-conflict");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("an unconfirmed save shows the last confirmed status and offers a retry; a retry after a lost answer changes nothing twice", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", rid);

  // 1. The request never reaches the server.
  await rp.route(STATUS_URL, (r) => r.abort("internetdisconnected"));
  await action(rp, "Postpone", codes[0]).click();
  const failed = orderCard(rp, codes[0]).getByTestId("status-failed");
  await expect(failed).toContainText("Could not confirm the save; showing the last confirmed status");
  await expect(failed).not.toContainText("Not saved");
  await expect(orderCard(rp, codes[0])).toHaveAttribute("data-status", "Pending");
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(codes);
  expect(await serverStatus(admin, rid, codes[0])).toBe("Pending");
  await shot(rp, "07-network-failure");
  await rp.unroute(STATUS_URL);
  await failed.getByRole("button", { name: "Retry: mark Postponed" }).click();
  await expect(rp.getByText(`${codes[0]} saved as Postponed.`)).toBeVisible();
  expect(await serverStatus(admin, rid, codes[0])).toBe("Postponed");

  // 2. The server saves, but the answer is lost: the retry is recognised as already done.
  await rp.route(STATUS_URL, async (r) => { await r.fetch(); await r.abort("connectionreset"); });
  await action(rp, "Postpone", codes[1]).click();
  await expect(orderCard(rp, codes[1]).getByTestId("status-failed")).toContainText("Could not confirm the save; showing the last confirmed status");
  expect(await serverStatus(admin, rid, codes[1])).toBe("Postponed");  // it did save
  const version = (await ordersOf(admin, rid))[codes[1]].version;
  await rp.unroute(STATUS_URL);
  await orderCard(rp, codes[1]).getByRole("button", { name: "Retry: mark Postponed" }).click();
  await expect(rp.getByText(`${codes[1]} was already Postponed; nothing changed.`)).toBeVisible();
  expect((await ordersOf(admin, rid))[codes[1]].version).toBe(version);  // no second change
  expect(await codesShown(rp.getByTestId("postponed"))).toEqual([codes[0], codes[1]].sort());
  await rp.context().close();
  await admin.ctx.dispose();
});

test("an order returned from Postponed without a saved position needs planning", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const { rid, codes } = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", rid);
  await action(rp, "Postpone", codes[0]).click();
  await expect(rp.getByText(`${codes[0]} saved as Postponed.`)).toBeVisible();
  await plan(admin, rid);  // version 2 holds it as Postponed: no stop position
  await rp.getByRole("button", { name: "Refresh" }).click();
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 2");
  await action(rp, "Return to Pending", codes[0]).click();
  await expect(rp.getByText(`${codes[0]} saved as Pending.`)).toBeVisible();
  const unsequenced = rp.getByTestId("unsequenced");
  expect(await codesShown(unsequenced)).toEqual([codes[0]]);
  await expect(unsequenced).toContainText("They need planning");
  expect(await codesShown(rp.getByTestId("sequence"))).not.toContain(codes[0]);
  await shot(rp, "08-needs-planning");
  const current = await admin.json<{ unplanned_pending: string[]; out_of_date: boolean }>(`/api/admin/rounds/${rid}/plan`);
  expect(current).toMatchObject({ unplanned_pending: [codes[0]], out_of_date: false });
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a late status answer for another round is ignored, and an expired session returns to sign-in", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const one = await soloRound(admin);
  const two = await soloRound(admin);
  const { rp } = await riderPage(browser, "p2_dev", one.rid);
  const slow = await gate(rp, STATUS_URL);
  await action(rp, "Postpone", one.codes[0]).click();
  await roundPicker(rp).selectOption(two.rid);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", two.rid);
  slow.release();
  await expect.poll(() => serverStatus(admin, one.rid, one.codes[0])).toBe("Postponed");  // saved on the server
  await rp.waitForTimeout(500);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", two.rid);
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(two.codes);
  await expect(rp.getByText(`${one.codes[0]} saved as Postponed.`)).toHaveCount(0);
  await slow.done();

  const me = await Api.of(rp);
  expect((await me.send("POST", "/api/auth/logout")).status()).toBe(200);
  await action(rp, "Postpone", two.codes[0]).click();
  await expect(rp).toHaveURL(/\/login$/, { timeout: 15_000 });
  expect(await serverStatus(admin, two.rid, two.codes[0])).toBe("Pending");
  await expectNoBrowserStorage(rp);
  await rp.context().close();
  await admin.ctx.dispose();
});
