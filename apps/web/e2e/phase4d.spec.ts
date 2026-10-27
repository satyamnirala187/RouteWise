// Step 4D browser verification (desktop 1280 px and mobile 390 px): the rider's own "Recalculate my route"
// and the shared-stop presentation, against the real API with recorded real-road matrices.
//
// MOCKED GEOLOCATION: no phone and no real GPS is involved. Positions are emulated by the browser (Playwright
// grantPermissions + setGeolocation) or by a scripted stub (see phase4d-helpers.ts). Real-device location is
// NOT tested here; the owner's phone check is separate. The opt-in real-Valhalla run is phase4d-live.spec.ts.
import { expect, test } from "@playwright/test";
import { Api, coords, ensureDepots, expectNoBrowserStorage, expectNoHorizontalOverflow, gotoRound, hold, newPage, prepareRound, PRIVATE_STRINGS, riderIds, signIn } from "./phase2-helpers";
import { codesShown, dirUrl, newRound, orderCard, ordersOf, plan, shooter } from "./phase3-helpers";
import {
  emulateGeolocation, FAR, geoLog, GPS, openChooser, openRider, P, plannedRound, PT, result, riderApi, section, sequenceCodes, UNRECORDED, viewOf,
} from "./phase4d-helpers";

test.afterEach(() => hold(false));

const shot = shooter("E2E_4D_SHOTS_DIR", "4d", "phase4");

test("a granted location (mocked geolocation) recalculates only my route, from that position, and says so", async ({ browser }) => {
  const { admin, rid, routes } = await plannedRound();
  const bilalBefore = await viewOf(await riderApi("p2_bilal"), rid);
  const planBefore = await admin.json<{ routes: { rider: string; stops: unknown }[] }>(`/api/admin/rounds/${rid}/plan`);
  const { rp, external, posts, consoleErrors } = await openRider(browser, "p2_asha", rid);
  await emulateGeolocation(rp, GPS);   // mocked geolocation: emulated by the browser, permission granted

  await expect(section(rp)).toContainText("Recalculate my route");
  expect((await geoLog(rp)).get).toBe(0);                  // nothing is requested until the rider taps
  await openChooser(rp);
  expect((await geoLog(rp)).get).toBe(0);                  // opening the choices does not read the position either
  await expect(rp.getByTestId("reroute-current")).toBeEnabled();
  await expect(rp.getByTestId("reroute-start")).toContainText("my configured start");
  await expect(rp.getByTestId("reroute-start")).toContainText("Not your current position");
  await expect(rp.getByTestId("reroute-last")).toHaveCount(0);   // no completed stop yet, so none is offered
  expect(posts).toHaveLength(0);                           // and nothing is preselected: no request was sent
  await shot(rp, "01-choose-a-starting-point");

  await rp.getByTestId("reroute-current").click();
  await expect(result(rp)).toContainText("Route recalculated from your current position (device location)");
  await expect(result(rp)).toHaveAttribute("data-tone", "ok");

  const log = await geoLog(rp);
  expect(log).toMatchObject({ get: 1, watch: 0 });          // one reading for one tap; never tracking
  expect(log.options[0]).toEqual({ enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
  expect(posts).toHaveLength(1);

  const me = await Api.of(rp);
  const view = await viewOf(me, rid);
  expect(view.plan!.rider_route!.revision).toMatchObject({ number: 1, trigger: "rider_request", origin_kind: "current_position" });
  expect([...sequenceCodes(view)].sort()).toEqual([...routes.Asha].sort());       // every own Pending order, no more, no less
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(sequenceCodes(view));  // the cards follow the saved revision
  await expect(rp.getByTestId("next-customer")).toHaveAttribute("data-order", sequenceCodes(view)[0]);

  // The Route card keeps its design and now reads the effective route.
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 1");
  await expect(rp.getByTestId("route-revision")).toContainText("Your route: revision 1");
  await expect(rp.getByTestId("route-revision")).toContainText("your current position (device location)");
  await expect(rp.getByTestId("route-distance")).toContainText("Planned road distance for revision 1 of your route");
  await expect(rp.getByTestId("route-distance")).toContainText("not the distance left");
  await expect(rp.getByTestId("route-distance")).toContainText("traffic-free estimate");

  // Nothing of the position stays anywhere on the page, and nobody else's route moved.
  const html = await rp.content();
  expect(html).not.toContain(String(GPS.lat));
  expect(html).not.toContain(String(GPS.lng));
  await expectNoBrowserStorage(rp);
  const bilalAfter = await viewOf(await riderApi("p2_bilal"), rid);
  expect(bilalAfter).toEqual(bilalBefore);
  const planAfter = await admin.json<{ routes: { rider: string; stops: unknown; rider_route: unknown }[] }>(`/api/admin/rounds/${rid}/plan`);
  expect(planAfter.routes.map((r) => [r.rider, r.stops])).toEqual(planBefore.routes.map((r) => [r.rider, r.stops]));  // the saved plan is unchanged
  expect(planAfter.routes.find((r) => r.rider === "Bilal")!.rider_route).toMatchObject({ revision: null });
  expect(external).toEqual([]);
  expect(consoleErrors).toEqual([]);
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "02-recalculated-from-the-device-position");
  await rp.context().close();
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// Location problems: each says what happened, sends nothing, and leaves the other starting points available.

test("every device-location problem is explained, sends nothing, and offers the other starting points", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const cases: { name: string; stub: Parameters<typeof openRider>[3]; says: RegExp }[] = [
    { name: "denied", stub: { stub: { kind: "error", code: 1 } }, says: /did not allow location for this page/ },
    { name: "unavailable", stub: { stub: { kind: "error", code: 2 } }, says: /could not work out its position/ },
    { name: "timeout", stub: { stub: { kind: "error", code: 3 } }, says: /did not give a position in time/ },
    { name: "inaccurate", stub: { stub: { kind: "fix", lat: GPS.lat, lng: GPS.lng, accuracy: 250 } }, says: /accurate only to about 250 m; the limit is 100 m/ },
    { name: "stale", stub: { stub: { kind: "fix", lat: GPS.lat, lng: GPS.lng, accuracy: 10, ageMs: 120_000 } }, says: /position that is 120 s old; the limit is 60 s/ },
  ];
  for (const c of cases) {
    const { rp, posts } = await openRider(browser, "p2_asha", rid, c.stub);
    await openChooser(rp);
    await rp.getByTestId("reroute-current").click();
    await expect(rp.getByTestId("reroute-problem")).toContainText(c.says);
    await expect(rp.getByTestId("reroute-problem")).not.toContainText(String(GPS.lat));
    expect((await geoLog(rp)).get).toBe(1);
    expect(posts, c.name).toHaveLength(0);                                          // nothing was sent
    await expect(rp.getByTestId("reroute-start")).toBeEnabled();                    // the fallback is still offered ...
    await expect(rp.getByTestId("reroute-current")).toBeEnabled();                  // ... and the rider may try the location again
    expect((await viewOf(await Api.of(rp), rid)).plan!.rider_route!.revision).toBeNull();   // ... and nothing was used meanwhile
    if (c.name === "denied") await shot(rp, "03-location-denied-with-fallback");
    await rp.context().close();
  }
  await admin.ctx.dispose();
});

test("a position the browser itself refuses (no permission granted) falls back only when the rider chooses", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);   // real browser behaviour: geolocation permission was never granted
  await openChooser(rp);
  await rp.getByTestId("reroute-current").click();
  await expect(rp.getByTestId("reroute-problem")).toBeVisible();
  expect(posts).toHaveLength(0);
  await rp.getByTestId("reroute-start").click();                    // the explicit fallback
  await expect(result(rp)).toContainText("Route recalculated from your configured start, not your current position");
  expect(posts).toHaveLength(1);
  expect(JSON.parse(posts[0].body!).origin).toEqual({ kind: "configured_start" });   // no coordinates, no position
  const rev = (await viewOf(await Api.of(rp), rid)).plan!.rider_route!.revision!;
  expect(rev).toMatchObject({ number: 1, origin_kind: "configured_start" });
  await shot(rp, "04-recalculated-from-the-configured-start");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a position the server refuses, or cannot route from, keeps the previous route and offers the fallbacks", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const before = sequenceCodes(await viewOf(await riderApi("p2_asha"), rid));
  for (const [name, at, says, kind] of [
    ["outside the service area", FAR, /outside the DU North Campus service area/, "refused"],
    ["no road data for the point", UNRECORDED, /routing engine is not available|failed/i, "failed"],
  ] as const) {
    const { rp, posts } = await openRider(browser, "p2_asha", rid, { stub: { kind: "fix", lat: at.lat, lng: at.lng, accuracy: 10 } });
    await openChooser(rp);
    await rp.getByTestId("reroute-current").click();
    await expect(result(rp)).toContainText(says);
    await expect(result(rp)).toContainText(kind === "failed" ? "Your previous route is still shown." : "Your route is unchanged");
    expect(posts, name).toHaveLength(1);                                           // the one tap sent one request, never a retry
    expect(sequenceCodes(await viewOf(await Api.of(rp), rid))).toEqual(before);    // the saved route did not change
    expect(await codesShown(rp.getByTestId("sequence"))).toEqual(before);
    if (kind === "refused") await expect(rp.getByTestId("reroute-start")).toBeEnabled();   // choices stay (retry offered)
    else { await rp.getByTestId("reroute-open").click(); await expect(rp.getByTestId("reroute-start")).toBeEnabled(); }
    const html = await rp.content();
    expect(html).not.toContain(String(at.lat));
    if (kind === "failed") await shot(rp, "05-recalculation-failed-previous-route-kept");
    await rp.context().close();
  }
  await admin.ctx.dispose();
});

test("on an insecure page, or without a geolocation API, the screen says location is unavailable and never asks", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  for (const [mode, geo, says] of [
    ["insecure", { insecure: true, stub: { kind: "fix", lat: GPS.lat, lng: GPS.lng } }, /Location isn't available on this connection/],
    ["unsupported", { absent: true }, /cannot share its location with this page/],
  ] as const) {
    const { rp, posts } = await openRider(browser, "p2_asha", rid, geo as Parameters<typeof openRider>[3]);
    await openChooser(rp);
    await expect(rp.getByTestId("reroute-support")).toHaveAttribute("data-support", mode);
    await expect(rp.getByTestId("reroute-support")).toContainText(says);
    if (mode === "insecure") {
      await expect(rp.getByTestId("reroute-support")).toContainText("HTTPS, or http://localhost");
      await expect(rp.getByTestId("reroute-support")).not.toContainText(/Wi-?Fi/i);   // never implies a Wi-Fi address supports GPS
    }
    await expect(rp.getByTestId("reroute-current")).toBeDisabled();
    await expect(rp.getByTestId("reroute-start")).toBeEnabled();
    if (mode === "insecure") expect((await geoLog(rp)).get).toBe(0);
    expect(posts).toHaveLength(0);
    if (mode === "insecure") await shot(rp, "06-insecure-page-location-unavailable");
    await rp.getByTestId("reroute-start").click();                                       // the fallback works
    await expect(result(rp)).toContainText("Route recalculated from your configured start");
    await rp.context().close();
  }
  await admin.ctx.dispose();
});

test("offline, recalculating is disabled with an explanation; nothing is queued", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  const before = await codesShown(rp.getByTestId("sequence"));
  await expect(rp.getByTestId("reroute-open")).toBeEnabled();
  await rp.context().setOffline(true);
  await expect(rp.getByTestId("reroute-offline")).toContainText("You are offline");
  await expect(rp.getByTestId("reroute-offline")).toContainText("nothing is queued");
  await expect(rp.getByTestId("reroute-open")).toBeDisabled();
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(before);                 // the saved route stays shown
  await shot(rp, "07-offline");
  await rp.context().setOffline(false);
  await expect(rp.getByTestId("reroute-offline")).toHaveCount(0);
  await expect(rp.getByTestId("reroute-open")).toBeEnabled();
  expect(posts).toHaveLength(0);                                                         // no request was made or queued meanwhile
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a double tap sends one recalculation, and the choices go away while it runs", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  await openChooser(rp);
  hold(true);                                                     // keep the run in progress so the double tap is observable
  await rp.getByTestId("reroute-start").dblclick();
  await expect(rp.getByTestId("reroute-progress")).toContainText("Recalculating your route");
  await expect(rp.getByTestId("reroute-choices")).toHaveCount(0);
  await expect(rp.getByTestId("reroute-open")).toHaveCount(0);
  await shot(rp, "08-recalculating");
  hold(false);
  await expect(result(rp)).toContainText("Route recalculated");
  expect(posts).toHaveLength(1);
  const runs = await (await riderApi("p2_asha")).json<{ plan: { rider_route: { revision: { number: number } } } }>(`/api/rider/rounds/${rid}/deliveries`);
  expect(runs.plan.rider_route.revision.number).toBe(1);          // one revision, not two
  await rp.context().close();
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// The run itself: recovery, blocked actions, uncertain outcomes, late answers.

test("refreshing the page follows the run already in progress instead of starting another", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  await openChooser(rp);
  hold(true);
  await rp.getByTestId("reroute-start").click();
  await expect(rp.getByTestId("reroute-progress")).toContainText("Recalculating your route");
  expect(posts).toHaveLength(1);
  await rp.reload();                                                                    // the rider reloads the page mid-run
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", rid);
  await expect(rp.getByTestId("reroute-progress")).toContainText("Recalculating your route");   // the run was discovered ...
  await expect(rp.getByTestId("reroute-choices")).toHaveCount(0);
  await expect(rp.getByTestId("reroute-open")).toHaveCount(0);                         // ... and no second one can be started
  await shot(rp, "09-run-discovered-after-refresh");
  hold(false);
  await expect(result(rp)).toContainText("A recalculation of your route finished");   // a run FOUND by reading the server: conservative wording
  await expect(result(rp)).not.toContainText("Route recalculated from");
  expect(posts).toHaveLength(1);                                                        // the page never started a run after the reload
  expect((await viewOf(await riderApi("p2_asha"), rid)).plan!.rider_route!.revision!.number).toBe(1);
  await rp.context().close();
  await admin.ctx.dispose();
});

test("while a recalculation runs every status and setup action waits; a status save in flight holds the recalculation back", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  const statusButtons = rp.locator("[data-testid=status-actions] button, [data-testid=next-unavailable]");
  const count = await statusButtons.count();
  expect(count).toBeGreaterThan(2);
  await openChooser(rp);
  hold(true);
  await rp.getByTestId("reroute-start").click();
  await expect(rp.getByTestId("reroute-progress")).toBeVisible();
  for (let i = 0; i < count; i++) await expect(statusButtons.nth(i)).toBeDisabled();
  await expect(rp.getByRole("button", { name: "Change destination" })).toBeDisabled();
  await expect(rp.getByTestId("setup-waits")).toContainText("wait while your route is being recalculated");
  await shot(rp, "10-status-and-setup-actions-wait");
  const before = await viewOf(await riderApi("p2_asha"), rid);
  expect(before.sequence.flatMap((s) => s.orders).every((o) => o.status === "Pending")).toBe(true);   // nothing could be changed
  hold(false);
  await expect(result(rp)).toContainText("Route recalculated");
  for (let i = 0; i < count; i++) await expect(statusButtons.nth(i)).toBeEnabled();
  await expect(rp.getByRole("button", { name: "Change destination" })).toBeEnabled();
  expect(posts).toHaveLength(1);

  // The other way round: while a status change is still being saved, recalculating cannot be started.
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await rp.route("**/api/rider/orders/*/status", async (route) => { await gate; await route.continue(); });
  await rp.getByTestId("next-unavailable").click();
  await expect(rp.getByTestId("next-unavailable")).toContainText("Saving…");
  await expect(rp.getByTestId("reroute-open")).toBeDisabled();
  release();
  await expect(rp.getByTestId("reroute-cue-postponed")).toBeVisible();
  expect(posts).toHaveLength(1);                                                        // and nothing recalculated by itself
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a lost answer to the request is an unknown outcome: the server is read first, and nothing is sent again by itself", async ({ browser }) => {
  // (a) the server received it and started the run, but the answer was lost: the run is discovered and followed.
  {
    const { admin, rid } = await plannedRound();
    const { rp, posts } = await openRider(browser, "p2_asha", rid);
    await rp.route(`**/api/rider/rounds/${rid}/reroute`, async (route) => { await route.fetch(); await route.abort("connectionreset"); });
    await openChooser(rp);
    hold(true);
    await rp.getByTestId("reroute-start").click();
    await expect(rp.getByTestId("reroute-progress")).toContainText("Recalculating your route");   // found by reading the state
    await rp.waitForTimeout(1200);
    expect(posts).toHaveLength(1);                                                                // no automatic retry
    hold(false);
    await expect(result(rp)).toContainText("A recalculation of your route finished");   // a run FOUND by reading the server: conservative wording
    await expect(result(rp)).not.toContainText("Route recalculated from");
    expect(posts).toHaveLength(1);
    expect((await viewOf(await riderApi("p2_asha"), rid)).plan!.rider_route!.revision!.number).toBe(1);
    await rp.context().close();
    await admin.ctx.dispose();
  }
  // (b) the request never reached the server: the read shows nothing happened; trying again is the rider's own explicit choice.
  {
    const { admin, rid } = await plannedRound();
    const { rp, posts } = await openRider(browser, "p2_asha", rid);
    await rp.route(`**/api/rider/rounds/${rid}/reroute`, (route) => route.abort("connectionreset"));
    await openChooser(rp);
    await rp.getByTestId("reroute-start").click();
    await expect(result(rp)).toContainText("Nothing was recalculated");
    await expect(result(rp)).toContainText("saved route is unchanged");
    await rp.waitForTimeout(1200);
    expect(posts).toHaveLength(1);
    await rp.unroute(`**/api/rider/rounds/${rid}/reroute`);
    await rp.getByTestId("reroute-open").click();
    await rp.getByTestId("reroute-start").click();                                               // an explicit second request
    await expect(result(rp)).toContainText("Route recalculated");
    expect(posts).toHaveLength(2);
    await rp.context().close();
    await admin.ctx.dispose();
  }
  // (c) the answer is lost and the state cannot be read either: only a read-only check is offered, never another request.
  {
    const { admin, rid } = await plannedRound();
    const { rp, posts } = await openRider(browser, "p2_asha", rid);
    await rp.route(`**/api/rider/rounds/${rid}/reroute`, async (route) => { await route.fetch(); await route.abort("connectionreset"); });
    await openChooser(rp);
    await rp.route(`**/api/rider/rounds/${rid}/deliveries`, (route) => route.abort("connectionreset"));
    await rp.getByTestId("reroute-start").click();
    await expect(result(rp)).toContainText("Could not confirm");
    await expect(rp.getByTestId("reroute-check-again")).toBeVisible();
    await expect(rp.getByTestId("reroute-choices")).toHaveCount(0);                              // no new request can be started yet
    await expect(rp.getByTestId("reroute-open")).toHaveCount(0);
    await shot(rp, "11-unknown-outcome-read-only-check");
    await rp.waitForTimeout(1200);
    expect(posts).toHaveLength(1);
    await rp.unroute(`**/api/rider/rounds/${rid}/deliveries`);
    await rp.getByTestId("reroute-check-again").click();
    // the server did start it (the first request got through), so the check finds the run or its saved result
    await expect(result(rp).or(rp.getByTestId("reroute-progress"))).toBeVisible();
    await expect(result(rp)).toContainText(/Route recalculated|Your route was recalculated|Nothing was recalculated/);
    expect(posts).toHaveLength(1);
    await rp.context().close();
    await admin.ctx.dispose();
  }
});

test("a late answer for another round never changes the selected round", async ({ browser }) => {
  const a = await plannedRound();
  const b = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", a.rid);
  const bCodes = sequenceCodes(await viewOf(await riderApi("p2_asha"), b.rid));
  await openChooser(rp);
  hold(true);
  await rp.getByTestId("reroute-start").click();
  await expect(rp.getByTestId("reroute-progress")).toBeVisible();
  await rp.getByRole("combobox", { name: "Round", exact: true }).selectOption(b.rid);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", b.rid);
  await expect(rp.getByTestId("reroute-progress")).toHaveCount(0);                      // round B shows nothing of round A's run
  hold(false);
  await rp.waitForTimeout(1500);                                                       // round A's run ends meanwhile
  await expect(result(rp)).toHaveCount(0);                                              // no confirmation appears on round B
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", b.rid);
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(bCodes);
  await expect(rp.getByTestId("route-revision")).toHaveCount(0);
  await rp.getByRole("combobox", { name: "Round", exact: true }).selectOption(a.rid);   // back on round A the saved result is shown
  await expect(rp.getByTestId("route-revision")).toContainText("Your route: revision 1");
  await expect(rp.getByTestId("reroute-progress")).toHaveCount(0);
  expect(posts).toHaveLength(1);
  await rp.context().close();
  await a.admin.ctx.dispose();
  await b.admin.ctx.dispose();
});

test("a run made stale by an admin edit is not saved, says why, and the previous route stays shown", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const before = sequenceCodes(await viewOf(await riderApi("p2_asha"), rid));
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  await openChooser(rp);
  hold(true);
  await rp.getByTestId("reroute-start").click();
  await expect(rp.getByTestId("reroute-progress")).toBeVisible();
  const mine = (await admin.json<{ id: string; order_code: string; version: number; location: { lat: number; lng: number } }[]>(`/api/admin/rounds/${rid}/orders`))
    .find((o) => o.order_code === before[0])!;
  await admin.ok("POST", `/api/admin/orders/${mine.id}/pin`, { version: mine.version, lat: mine.location.lat + 0.0001, lng: mine.location.lng });
  hold(false);
  await expect(result(rp)).toContainText("Not saved: something changed meanwhile");
  await expect(result(rp)).toContainText("Your previous route is still shown.");
  await expect(rp.getByTestId("reroute-blocked")).toBeVisible();                       // the round is now out of date: said plainly
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(before);
  expect(posts).toHaveLength(1);
  expect((await viewOf(await riderApi("p2_asha"), rid)).plan!.rider_route!.revision).toBeNull();   // nothing was saved
  await shot(rp, "12-run-stale-previous-route-kept");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a busy planner (mocked 503 answer) starts nothing; the rider retries by hand", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  await rp.route(`**/api/rider/rounds/${rid}/reroute`, (route) => route.fulfill({ status: 503, contentType: "application/json",
    body: JSON.stringify({ detail: { code: "PLANNING_BUSY", message: "The planner is busy; try again in a moment. Your current route is unchanged.", details: [] } }) }));
  await openChooser(rp);
  await rp.getByTestId("reroute-start").click();
  await expect(result(rp)).toContainText("planner is busy");
  await expect(rp.getByTestId("reroute-start")).toBeEnabled();                          // the choices stay: it is the rider's call
  await rp.waitForTimeout(1200);
  expect(posts).toHaveLength(1);                                                        // never retried by the page
  await rp.unroute(`**/api/rider/rounds/${rid}/reroute`);
  await rp.getByTestId("reroute-start").click();
  await expect(result(rp)).toContainText("Route recalculated");
  expect(posts).toHaveLength(2);
  await rp.context().close();
  await admin.ctx.dispose();
});

test("interrupted, replanned and unroutable run answers (mocked server answers) say what happened", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp } = await openRider(browser, "p2_asha", rid);
  const answers: [object, RegExp][] = [
    [{ state: "interrupted", error: { code: "INTERRUPTED", message: "x", details: [] } }, /Recalculation interrupted[\s\S]*did not finish[\s\S]*Your previous route is still shown/],
    [{ state: "stale", error: { code: "ROUND_REPLANNED", message: "x", details: [] } }, /Not saved[\s\S]*Your admin replanned the round/],
    [{ state: "failed", error: { code: "UNROUTABLE_ORIGIN", message: "x", details: [] } }, /Could not recalculate[\s\S]*No road was found near that starting point/],
  ];
  let next = 0;
  // Both the start and the run reads are mocked, so no real run exists: only the screen's wording is under test here.
  await rp.route(`**/api/rider/rounds/${rid}/reroute`, (route) => route.fulfill({ status: 202, contentType: "application/json",
    body: JSON.stringify({ id: "run-x", round_id: rid, state: "queued", origin_kind: "configured_start", requested_at: new Date().toISOString(), finished_at: null, error: null, revision: null }) }));
  await rp.route("**/api/rider/reroutes/*", (route) => route.fulfill({ status: 200, contentType: "application/json",
    body: JSON.stringify({ id: "run-x", round_id: rid, origin_kind: "configured_start", requested_at: new Date().toISOString(), finished_at: null, revision: null, ...answers[next][0] }) }));
  for (let i = 0; i < answers.length; i++) {
    next = i;
    await rp.getByTestId("reroute-open").click();
    await rp.getByTestId("reroute-start").click();
    await expect(result(rp)).toContainText(answers[i][1]);
    await expect(result(rp)).toHaveAttribute("data-tone", i === 2 ? "error" : "warn");
    await rp.getByRole("button", { name: "Dismiss" }).click();
  }
  await rp.context().close();
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// Shared stops (A21): one container, one Navigate, the customers' own cards and statuses.

/** Another rider's view without the round-wide flag "deliveries were updated since the plan" (any rider's progress sets it; it carries no other rider's data). */
const withoutRoundProgress = (v: Awaited<ReturnType<typeof viewOf>>) => ({ ...v, plan: v.plan && { ...v.plan, progress_since_plan: undefined } });

const named = async (admin: Api, rid: string) =>
  Object.fromEntries(Object.values(await ordersOf(admin, rid)).map((o) => [o.customer_name, o]));

async function adminPlanPage(browser: Parameters<typeof openRider>[0], rid: string) {
  const ap = await newPage(browser);
  await signIn(ap, "admin_e2e");
  await gotoRound(ap, "/admin/plan", rid);
  await expect(ap.getByTestId("plan-view")).toBeVisible();
  return ap;
}

test("a shared stop is one container with one Navigate and each customer's own card; partial completion leaves the others alone", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "last_stop" }]);
  const asha = (await riderIds(admin)).p2_asha;
  const [n1, n2] = ["P2 Customer 1", "P2 Customer 2"];
  let o = await named(admin, rid);
  await admin.ok("POST", `/api/admin/orders/${o[n2].id}/pin`, { version: o[n2].version, lat: PT.kirori_mal.lat, lng: PT.kirori_mal.lng });
  for (const n of [n1, n2]) { o = await named(admin, rid); await admin.ok("PUT", `/api/admin/orders/${o[n].id}/lock`, { version: o[n].version, rider_id: asha }); }
  o = await named(admin, rid);
  await admin.ok("POST", `/api/admin/rounds/${rid}/stop-groups`, { orders: [n1, n2].map((n) => ({ id: o[n].id, version: o[n].version })) });
  o = await named(admin, rid);
  await admin.ok("PUT", `/api/admin/orders/${o[n2].id}/priority`, { version: o[n2].version, first_priority: true });   // the second customer leads the group
  await plan(admin, rid);
  o = await named(admin, rid);
  const [c1, c2] = [o[n1].order_code, o[n2].order_code];
  const bilalBefore = await viewOf(await riderApi("p2_bilal"), rid);

  const { rp, external, consoleErrors } = await openRider(browser, "p2_asha", rid);
  const shared = rp.locator('[data-testid=rider-stop][data-customers="2"]');
  await expect(shared).toHaveCount(1);
  await expect(shared.getByTestId("stop-customers")).toHaveText("2 customers at this location");
  await expect(shared.getByTestId("navigate-link")).toHaveCount(1);                                   // exactly one Navigate for the stop
  await expect(shared.getByTestId("navigate-link")).toHaveAttribute("href", dirUrl(PT.kirori_mal.lat, PT.kirori_mal.lng));
  await expect(shared.getByTestId("rider-order")).toHaveCount(2);
  await expect(shared.getByTestId("rider-order").getByTestId("navigate-link")).toHaveCount(0);        // none per customer
  expect(await codesShown(shared)).toEqual([c2, c1]);                                                 // the priority customer leads the stop
  await expect(shared.getByTestId("next-customer-badge")).toHaveCount(1);
  await expect(orderCard(rp, c2).getByTestId("next-customer-badge")).toBeVisible();
  for (const c of [c1, c2]) {                                                                         // each keeps their own details and actions
    await expect(orderCard(rp, c).getByTestId("call-link")).toHaveCount(1);
    await expect(orderCard(rp, c).getByTestId("contact")).toBeVisible();
    await expect(orderCard(rp, c).getByRole("button", { name: new RegExp(`^(Mark delivered|Postpone): ${c}$`) })).toHaveCount(2);
  }
  await expect(rp.getByTestId("next-customer")).toHaveAttribute("data-order", c2);                    // the panel follows the server's order
  await expect(rp.getByTestId("next-customer")).toContainText("1 more Pending customer at this stop");
  const stops = rp.locator("[data-testid=sequence] [data-testid=rider-stop]");
  await expect(rp.locator("[data-testid=sequence] [data-testid=navigate-link]")).toHaveCount(await stops.count());   // one Navigate per stop
  await expectNoHorizontalOverflow(rp);
  await shot(rp, "13-shared-stop");

  const seq = Number(await shared.getAttribute("data-stop"));
  const v1 = (await viewOf(await Api.of(rp), rid)).sequence.flatMap((x) => x.orders).find((x) => x.order_code === c1)!;
  // Deliver the first customer (a second tap confirms): the other one stays in the same stop, unchanged.
  await rp.getByRole("button", { name: `Mark delivered: ${c2}` }).click();
  await orderCard(rp, c2).getByRole("button", { name: "Yes, delivered" }).click();
  await expect(rp.getByRole("status").filter({ hasText: `${c2} saved as Completed.` })).toBeVisible();
  const remaining = rp.locator(`[data-testid=rider-stop][data-stop="${seq}"]`);
  await expect(remaining).toHaveAttribute("data-customers", "1");                                     // the stop remains while a customer is Pending
  await expect(remaining.getByTestId("navigate-link")).toHaveCount(1);
  await expect(remaining.getByTestId("navigate-link")).toHaveAttribute("href", dirUrl(PT.kirori_mal.lat, PT.kirori_mal.lng));
  await expect(orderCard(rp, c1)).toHaveAttribute("data-status", "Pending");
  await expect(orderCard(rp, c1).getByTestId("shared-note")).toContainText("Shared location");
  await expect(rp.getByTestId("next-customer")).toHaveAttribute("data-order", c1);
  const after1 = (await viewOf(await Api.of(rp), rid)).sequence.flatMap((x) => x.orders).find((x) => x.order_code === c1)!;
  expect(after1).toEqual(v1);                                                                         // the other customer's order is untouched
  expect(await codesShown(rp.getByTestId("completed"))).toEqual([c2]);
  await shot(rp, "14-shared-stop-after-one-delivery");

  // Postponing the last Pending customer takes the stop out of the route; it stays held, not Completed.
  await rp.getByTestId("next-unavailable").click();
  await expect(rp.getByRole("status").filter({ hasText: `${c1} saved as Postponed.` })).toBeVisible();
  await expect(rp.locator(`[data-testid=rider-stop][data-stop="${seq}"]`)).toHaveCount(0);
  expect(await codesShown(rp.getByTestId("postponed"))).toEqual([c1]);
  expect(await codesShown(rp.getByTestId("completed"))).toEqual([c2]);
  expect(withoutRoundProgress(await viewOf(await riderApi("p2_bilal"), rid))).toEqual(withoutRoundProgress(bilalBefore));   // the other rider's data did not move
  expect(external).toEqual([]);
  expect(consoleErrors).toEqual([]);
  await rp.context().close();
  await admin.ctx.dispose();
});

test("identical pins that were never grouped stay separate stops, each with its own Navigate", async ({ browser }) => {
  const admin = await Api.login("admin_e2e");
  await ensureDepots(admin);
  const rid = await newRound(admin);
  await prepareRound(admin, rid, [
    { user: "p2_asha", vehicle: "scooter", capacity: 5, start: "office", kind: "home", at: P.home_r1 },
    { user: "p2_bilal", vehicle: "bike", capacity: 5, start: "warehouse", kind: "last_stop" }]);
  const asha = (await riderIds(admin)).p2_asha;
  const [n1, n2] = ["P2 Customer 1", "P2 Customer 2"];
  let o = await named(admin, rid);
  await admin.ok("POST", `/api/admin/orders/${o[n2].id}/pin`, { version: o[n2].version, lat: PT.kirori_mal.lat, lng: PT.kirori_mal.lng });
  for (const n of [n1, n2]) { o = await named(admin, rid); await admin.ok("PUT", `/api/admin/orders/${o[n].id}/lock`, { version: o[n].version, rider_id: asha }); }
  await plan(admin, rid);
  o = await named(admin, rid);
  const { rp } = await openRider(browser, "p2_asha", rid);
  const container = (code: string) => orderCard(rp, code).locator("xpath=ancestor::*[@data-testid='rider-stop']");
  await expect(container(o[n1].order_code)).toHaveAttribute("data-customers", "1");
  await expect(container(o[n2].order_code)).toHaveAttribute("data-customers", "1");
  expect(await container(o[n1].order_code).getAttribute("data-stop")).not.toBe(await container(o[n2].order_code).getAttribute("data-stop"));
  for (const n of [n1, n2]) {
    await expect(container(o[n].order_code).getByTestId("navigate-link")).toHaveCount(1);
    await expect(container(o[n].order_code).getByTestId("navigate-link")).toHaveAttribute("href", dirUrl(PT.kirori_mal.lat, PT.kirori_mal.lng));
  }
  await expect(rp.getByTestId("stop-customers")).toHaveCount(0);                                      // nothing was merged on the screen
  await rp.context().close();
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// Postpone (A18), orders outside the saved route, the last completed stop, destination changes (A20), isolation.

test("after a Postpone the rider may keep the saved order or recalculate; nothing is ever recalculated by itself", async ({ browser }) => {
  const { admin, rid, routes } = await plannedRound();
  const bilalBefore = await viewOf(await riderApi("p2_bilal"), rid);
  const planBefore = await admin.json<{ routes: { rider: string; stops: unknown }[] }>(`/api/admin/rounds/${rid}/plan`);
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  const [first, second] = routes.Asha;

  await rp.getByTestId("next-unavailable").click();
  await expect(rp.getByRole("status").filter({ hasText: `${first} saved as Postponed.` })).toBeVisible();
  await expect(rp.getByTestId("reroute-cue-postponed")).toContainText(`${first} was saved as Postponed`);
  await expect(rp.getByTestId("reroute-cue-postponed")).toContainText("nothing is recalculated unless you choose to");
  await shot(rp, "15-after-postpone-keep-or-recalculate");
  await rp.waitForTimeout(1500);
  expect(posts).toHaveLength(0);                                                                      // never automatic
  expect(sequenceCodes(await viewOf(await riderApi("p2_asha"), rid))).toEqual(routes.Asha.filter((c) => c !== first));   // the saved order stands

  await rp.getByTestId("reroute-keep").click();                                                       // keep the current order
  await expect(rp.getByTestId("reroute-cue-postponed")).toHaveCount(0);
  expect(await codesShown(rp.getByTestId("sequence"))).toEqual(routes.Asha.filter((c) => c !== first));
  expect(posts).toHaveLength(0);

  await rp.getByTestId("next-unavailable").click();                                                   // a second Postpone: now recalculate
  await expect(rp.getByTestId("reroute-cue-postponed")).toContainText(`${second} was saved as Postponed`);
  await rp.getByTestId("reroute-recalculate").click();
  await expect(rp.getByTestId("reroute-cue-postponed")).toHaveCount(0);
  await rp.getByTestId("reroute-start").click();
  await expect(result(rp)).toContainText("Route recalculated from your configured start, not your current position");
  expect(posts).toHaveLength(1);

  const mine = await viewOf(await riderApi("p2_asha"), rid);
  expect([...sequenceCodes(mine)].sort()).toEqual(routes.Asha.filter((c) => c !== first && c !== second).sort());   // every own Pending order
  expect(mine.postponed.map((x) => x.order_code).sort()).toEqual([first, second].sort());              // held orders stay with the rider, out of the route
  expect(withoutRoundProgress(await viewOf(await riderApi("p2_bilal"), rid))).toEqual(withoutRoundProgress(bilalBefore));    // rider B is untouched
  const planAfter = await admin.json<{ routes: { rider: string; stops: unknown }[] }>(`/api/admin/rounds/${rid}/plan`);
  expect(planAfter.routes.map((r) => [r.rider, r.stops])).toEqual(planBefore.routes.map((r) => [r.rider, r.stops]));   // the admin's saved plan is unchanged

  const ap = await adminPlanPage(browser, rid);
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-revision")).toContainText("Recalculated by the rider");
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-revision")).toContainText("from their configured start");
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-revision")).toContainText("not the distance left");
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Bilal" }).getByTestId("rider-revision")).toHaveCount(0);
  const stopsShown = ap.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-route-stop");
  expect(await stopsShown.count()).toBe(sequenceCodes(mine).length);
  const html = await ap.content();
  for (const s of PRIVATE_STRINGS) expect(html).not.toContain(s);
  await shot(ap, "16-admin-effective-route");
  await ap.context().close();
  await rp.context().close();
  await admin.ctx.dispose();
});

test("an order returned to Pending outside the saved route is offered for recalculation and placed by it", async ({ browser }) => {
  const { admin, rid, routes } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  const first = routes.Asha[0];
  await rp.getByTestId("next-unavailable").click();
  await rp.getByTestId("reroute-recalculate").click();
  await rp.getByTestId("reroute-start").click();
  await expect(result(rp)).toContainText("Route recalculated");                                       // revision 1 leaves the postponed order out
  await rp.getByRole("button", { name: `Return to Pending: ${first}` }).click();
  await expect(rp.getByRole("status").filter({ hasText: `${first} saved as Pending.` })).toBeVisible();
  expect(await codesShown(rp.getByTestId("unsequenced"))).toEqual([first]);                           // "not in your saved route"
  await expect(rp.getByTestId("reroute-cue-unsequenced")).toContainText("1 Pending order is not in your saved route");
  await expect(rp.getByTestId("next-empty").or(rp.getByTestId("next-customer"))).toBeVisible();
  await shot(rp, "17-order-outside-the-saved-route");
  expect(posts).toHaveLength(1);                                                                      // returning it recalculated nothing
  await rp.getByTestId("reroute-open").click();
  await rp.getByTestId("reroute-start").click();
  await expect(result(rp)).toContainText("Route recalculated");
  await expect(rp.getByTestId("unsequenced")).toHaveCount(0);
  expect(sequenceCodes(await viewOf(await riderApi("p2_asha"), rid)).sort()).toEqual([...routes.Asha].sort());   // it is routed again
  expect(posts).toHaveLength(2);
  await rp.context().close();
  await admin.ctx.dispose();
});

test("after a delivery the last completed stop is offered, labelled as not the current position, and the configured start no longer is", async ({ browser }) => {
  const { admin, rid, routes } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  const done = routes.Asha[0];
  await rp.getByRole("button", { name: `Mark delivered: ${done}` }).click();
  await orderCard(rp, done).getByRole("button", { name: "Yes, delivered" }).click();
  await expect(rp.getByRole("status").filter({ hasText: `${done} saved as Completed.` })).toBeVisible();
  await openChooser(rp);
  await expect(rp.getByTestId("reroute-last")).toContainText(`From my last completed stop: ${done}`);
  await expect(rp.getByTestId("reroute-last")).toContainText("Not your current position");
  await expect(rp.getByTestId("reroute-start")).toHaveCount(0);                                       // not offered once a completed stop exists
  await shot(rp, "18-last-completed-stop-offered");
  await rp.getByTestId("reroute-last").click();
  await expect(result(rp)).toContainText("Route recalculated from your last completed stop, not your current position");
  const view = await viewOf(await riderApi("p2_asha"), rid);
  expect(view.plan!.rider_route!.revision).toMatchObject({ number: 1, origin_kind: "last_completed_stop" });
  expect(view.completed.map((x) => x.order_code)).toEqual([done]);                                    // history kept, outside the route
  expect([...sequenceCodes(view)].sort()).toEqual(routes.Asha.filter((c) => c !== done).sort());
  expect(posts).toHaveLength(1);
  expect(JSON.parse(posts[0].body!).origin).toMatchObject({ kind: "last_completed_stop" });
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a changed destination says the saved route still ends at the previous one until the rider confirms and recalculates; only they are affected", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const asha = await openRider(browser, "p2_asha", rid);
  const bilal = await openRider(browser, "p2_bilal", rid);
  const bilalSeq = await codesShown(bilal.rp.getByTestId("sequence"));
  const destination = asha.rp.locator(`[data-testid=destination-card][data-round="${rid}"]`);
  const ap = await adminPlanPage(browser, rid);

  // 1. New Home coordinates under the same kind: only the server's metadata can tell.
  await destination.getByRole("button", { name: "Change destination" }).click();
  await destination.getByLabel(/^Home location/).fill(coords(P.custom_r2));
  await destination.getByRole("button", { name: "Save destination" }).click();
  await expect(asha.rp.getByTestId("route-awaiting")).toContainText("You changed the location of your Home destination");
  await expect(asha.rp.getByTestId("route-awaiting")).toContainText("still ends at the previous Home location until you recalculate");
  await expect(asha.rp.getByTestId("route-awaiting")).toContainText("the stops and distance below are for the saved route");
  await expect(asha.rp.getByTestId("reroute-blocked")).toHaveAttribute("data-code", "NOT_CONFIRMED");   // confirm first
  await expect(asha.rp.getByTestId("reroute-cue-awaiting")).toContainText("Confirm your new setup above first");
  await expect(asha.rp.getByTestId("reroute-open")).toHaveCount(0);
  await shot(asha.rp, "19-destination-changed-saved-route-ends-at-the-previous");

  // Rider B and the admin: nothing for B to confirm or recalculate; the admin sees only Asha's route awaiting.
  await bilal.rp.getByRole("button", { name: "Refresh" }).click();
  await expect(bilal.rp.getByTestId("route-awaiting")).toHaveCount(0);
  await expect(bilal.rp.getByTestId("reroute-cue-awaiting")).toHaveCount(0);
  await expect(bilal.rp.getByTestId("plan-out-of-date")).toHaveCount(0);
  await expect(bilal.rp.getByTestId("reroute-open")).toBeEnabled();
  expect(await codesShown(bilal.rp.getByTestId("sequence"))).toEqual(bilalSeq);
  expect((await viewOf(await riderApi("p2_bilal"), rid)).plan!.rider_route!.awaiting_recalculation).toBeNull();
  await ap.reload();
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-awaiting-recalculation")).toBeVisible();
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Bilal" }).getByTestId("rider-awaiting-recalculation")).toHaveCount(0);
  await expect(ap.getByTestId("out-of-date")).toHaveCount(0);

  // 2. Confirm, then recalculate: the route now ends at the new location.
  await destination.getByRole("button", { name: "Confirm this setup" }).click();
  await expect(asha.rp.getByTestId("reroute-cue-awaiting")).toContainText("Recalculate to route to your new destination");
  await asha.rp.getByTestId("reroute-open").click();
  await asha.rp.getByTestId("reroute-start").click();
  await expect(result(asha.rp)).toContainText("Route recalculated");
  await expect(asha.rp.getByTestId("route-awaiting")).toHaveCount(0);
  const v1 = await viewOf(await riderApi("p2_asha"), rid);
  expect(v1.plan!.rider_route).toMatchObject({ awaiting_recalculation: null, revision: { number: 1, trigger: "endpoint_change" } });

  // 3. A different kind: Home to Warehouse names both.
  await destination.getByRole("button", { name: "Change destination" }).click();
  await destination.getByRole("radio", { name: /^Warehouse/ }).check();
  await destination.getByRole("button", { name: "Save destination" }).click();
  await expect(asha.rp.getByTestId("route-awaiting")).toContainText("You changed your destination to Warehouse. Your saved route still ends at Home until you recalculate.");
  await destination.getByRole("button", { name: "Confirm this setup" }).click();
  await asha.rp.getByTestId("reroute-open").click();
  await asha.rp.getByTestId("reroute-start").click();
  await expect(result(asha.rp)).toContainText("Route recalculated");
  await expect(asha.rp.getByTestId("route-awaiting")).toHaveCount(0);
  await expect(asha.rp.getByTestId("route-ends")).toContainText("Warehouse");
  expect((await viewOf(await riderApi("p2_asha"), rid)).plan!.rider_route).toMatchObject({ destination: { kind: "warehouse" }, revision: { number: 2 } });
  expect(await codesShown(bilal.rp.getByTestId("sequence"))).toEqual(bilalSeq);

  await ap.reload();
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-awaiting-recalculation")).toHaveCount(0);
  await expect(ap.getByTestId("plan-route").filter({ hasText: "Asha" }).getByTestId("rider-revision")).toContainText("ends at Warehouse");
  const html = await ap.content();
  for (const s of [...PRIVATE_STRINGS, String(P.custom_r2.lat), String(P.custom_r2.lng)]) expect(html).not.toContain(s);   // never a private endpoint
  await shot(ap, "20-admin-after-endpoint-recalculation");
  for (const page of [asha.rp, bilal.rp, ap]) await page.context().close();
  await admin.ctx.dispose();
});

test("another rider's run, round or route can neither be read nor started, and never appears on a rider's screen", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const solo = await newRound(admin);                                                    // a round only Asha takes part in
  await prepareRound(admin, solo, [{ user: "p2_asha", vehicle: "scooter", capacity: 8, start: "office", kind: "home", at: P.home_r1 }]);
  await plan(admin, solo);
  const ashaApi = await riderApi("p2_asha");
  const run = await ashaApi.ok<{ id: string }>("POST", `/api/rider/rounds/${rid}/reroute`,
    { origin: { kind: "configured_start" }, expected_plan_version: 1, expected_revision: 0 });
  const bilalApi = await riderApi("p2_bilal");
  const missing = "00000000-0000-4000-8000-000000000000";
  const guessed = await bilalApi.get(`/api/rider/reroutes/${run.id}`);
  const absent = await bilalApi.get(`/api/rider/reroutes/${missing}`);
  expect(guessed.status()).toBe(404);
  expect(await guessed.text()).toBe(await absent.text());                                // indistinguishable from a run that does not exist
  const body = { origin: { kind: "configured_start" }, expected_plan_version: 1, expected_revision: 0 };
  const other = await bilalApi.send("POST", `/api/rider/rounds/${solo}/reroute`, body);
  const nowhere = await bilalApi.send("POST", `/api/rider/rounds/${missing}/reroute`, body);
  expect(other.status()).toBe(404);
  expect(await other.text()).toBe(await nowhere.text());
  expect((await bilalApi.get(`/api/rider/rounds/${solo}/deliveries`)).status()).toBe(404);
  expect((await bilalApi.get(`/api/rider/rounds/${rid}/deliveries`)).ok()).toBe(true);
  for (let i = 0; i < 100; i++) {                                                         // let Asha's run finish
    if ((await ashaApi.json<{ state: string }>(`/api/rider/reroutes/${run.id}`)).state === "succeeded") break;
    await new Promise((r) => setTimeout(r, 100));
  }
  const { rp } = await openRider(browser, "p2_bilal", rid);
  await expect(rp.getByTestId("route-revision")).toHaveCount(0);                          // Asha's recalculation is not Bilal's
  await expect(rp.getByTestId("reroute-progress")).toHaveCount(0);
  const ashaCodes = sequenceCodes(await viewOf(ashaApi, rid));
  const html = await rp.content();
  for (const c of ashaCodes) expect(html).not.toContain(c);                               // none of Asha's orders on Bilal's screen
  await rp.context().close();
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// Lifecycle: cancel, sign-out and an expired session.

test("cancelling the location wait, signing out mid-run and an expired session leave nothing running or kept", async ({ browser }) => {
  const { admin, rid } = await plannedRound();

  // Cancelling the wait for a position: back to the choices, nothing sent, nothing remembered.
  {
    const { rp, posts } = await openRider(browser, "p2_asha", rid, { stub: { kind: "hang" } });   // the phone never answers (mocked geolocation)
    await openChooser(rp);
    await rp.getByTestId("reroute-current").click();
    await expect(rp.getByTestId("reroute-progress")).toHaveAttribute("data-phase", "locating");
    await expect(rp.getByTestId("reroute-progress")).toContainText("allow location access");
    await expect(rp.locator("[data-testid=next-unavailable]")).toBeDisabled();                  // status actions wait while locating
    await rp.getByTestId("reroute-cancel").click();
    await expect(rp.getByTestId("reroute-choices")).toBeVisible();
    await expect(rp.getByTestId("reroute-problem")).toHaveCount(0);
    await expect(rp.locator("[data-testid=next-unavailable]")).toBeEnabled();
    expect(posts).toHaveLength(0);
    expect((await geoLog(rp)).get).toBe(1);
    await expectNoBrowserStorage(rp);
    await rp.context().close();
  }
  // Signing out while a run is in progress: reading stops at once, and nothing else is sent.
  {
    const { rp, posts } = await openRider(browser, "p2_asha", rid);
    let reads = 0;
    rp.on("request", (r) => { if (/\/api\/rider\/reroutes\//.test(r.url())) reads += 1; });
    await openChooser(rp);
    hold(true);
    await rp.getByTestId("reroute-start").click();
    await expect(rp.getByTestId("reroute-progress")).toContainText("Recalculating");
    await expect.poll(() => reads).toBeGreaterThan(0);
    await rp.getByRole("button", { name: "Sign out" }).click();
    await expect(rp).toHaveURL(/\/login$/);
    const seen = reads;
    await rp.waitForTimeout(2500);
    expect(reads - seen).toBeLessThanOrEqual(1);                                                // at most the read already in flight
    expect(posts).toHaveLength(1);
    await expectNoBrowserStorage(rp);
    await rp.context().close();
    hold(false);
  }
  // An expired session while reading a run: the rider is returned to sign-in, not left waiting.
  {
    const { rp } = await openRider(browser, "p2_bilal", rid);
    await rp.route("**/api/rider/reroutes/*", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Session expired; sign in again" }) }));
    await openChooser(rp);
    await rp.getByTestId("reroute-start").click();
    await expect(rp).toHaveURL(/\/login$/);
    await rp.context().close();
  }
  await admin.ctx.dispose();
});

// ---------------------------------------------------------------------------------------------------------------
// Correction pass: plan version AND revision identify a route; what is unresolved outlives the message about it.

test("dismissing the message about an unknown outcome, or confirming a status change, never allows another recalculation until the server has been read", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  await rp.route(`**/api/rider/rounds/${rid}/reroute`, async (route) => { await route.fetch(); await route.abort("connectionreset"); });
  await openChooser(rp);
  await rp.route(`**/api/rider/rounds/${rid}/deliveries`, (route) => route.abort("connectionreset"));   // the state cannot be read either
  await rp.getByTestId("reroute-start").click();
  await expect(result(rp)).toContainText("Could not confirm");

  await rp.getByRole("button", { name: "Dismiss" }).click();                             // the message goes ...
  await expect(result(rp)).toHaveCount(0);
  await expect(rp.getByTestId("reroute-unresolved")).toBeVisible();                       // ... the uncertainty and the read-only check stay
  await expect(rp.getByTestId("reroute-check-again")).toBeVisible();
  await expect(rp.getByTestId("reroute-choices")).toHaveCount(0);
  await expect(rp.getByTestId("reroute-open")).toHaveCount(0);
  await shot(rp, "21-unresolved-after-dismiss");

  // A confirmed status change (its answer carries a view) must not expose new choices either.
  await rp.getByTestId("next-unavailable").click();
  await expect(rp.getByRole("status").filter({ hasText: /^RW-\d+ saved as Postponed\./ })).toBeVisible();
  await expect(rp.getByTestId("reroute-unresolved")).toBeVisible();
  await expect(rp.getByTestId("reroute-recalculate")).toBeDisabled();                    // the Postpone offer cannot start one either
  await expect(rp.getByTestId("reroute-open")).toHaveCount(0);
  expect(posts).toHaveLength(1);

  await rp.getByTestId("reroute-check-again").click();                                    // the read still fails: still unresolved
  await expect(result(rp)).toContainText("Could not confirm");
  await expect(rp.getByTestId("reroute-choices")).toHaveCount(0);
  await rp.getByRole("button", { name: "Dismiss" }).click();
  await expect(rp.getByTestId("reroute-unresolved")).toBeVisible();
  await rp.waitForTimeout(1000);
  expect(posts).toHaveLength(1);                                                          // no second recalculation of any kind

  await rp.unroute(`**/api/rider/rounds/${rid}/deliveries`);                              // the server can be read: the state is established
  await rp.getByTestId("reroute-check-again").click();
  await expect(rp.getByTestId("reroute-unresolved")).toHaveCount(0);
  await expect(result(rp)).toContainText("Your route was recalculated");                  // the lost request had saved revision 1 on plan 1
  await expect(result(rp)).toContainText("cannot be matched to it exactly");
  await expect(rp.getByTestId("reroute-open")).toBeEnabled();                             // and the actions are back (the Postpone offer ended with the check)
  expect(posts).toHaveLength(1);
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a recalculation that finished, then an admin replan before the new route is loaded, is not shown as the requested route (revision numbers reused)", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  let holdViews = false, reached = false;
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await rp.route(`**/api/rider/rounds/${rid}/deliveries`, async (route) => { if (holdViews) { reached = true; await gate; } await route.continue(); });
  await openChooser(rp);
  holdViews = true;
  await rp.getByTestId("reroute-start").click();
  await expect.poll(() => reached).toBe(true);                                           // the run ended; reading the effective view is held

  // Meanwhile the admin replans (plan 2) and the rider already holds a revision 1 on plan 2: the same number as the requested route's.
  await plan(admin, rid);
  const me = await riderApi("p2_asha");
  const run = await me.ok<{ id: string }>("POST", `/api/rider/rounds/${rid}/reroute`, { origin: { kind: "configured_start" }, expected_plan_version: 2, expected_revision: 0 });
  for (let i = 0; i < 100 && (await me.json<{ state: string }>(`/api/rider/reroutes/${run.id}`)).state !== "succeeded"; i++) await rp.waitForTimeout(100);
  const now = await viewOf(me, rid);
  expect(now.plan).toMatchObject({ version: 2, rider_route: { revision: { number: 1 } } });
  release();

  await expect(result(rp)).toContainText("Your admin replanned the round");
  await expect(result(rp)).toContainText("plan version 1");
  await expect(result(rp)).toContainText("version 2");
  await expect(result(rp)).toContainText("Your requested route is not shown");
  await expect(result(rp)).not.toContainText("Route recalculated from");
  await expect(result(rp)).not.toContainText("Your new order is shown below");
  await expect(rp.getByTestId("reroute-unresolved")).toHaveCount(0);                      // the server state is established: plan 2's route
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 2");
  expect(posts).toHaveLength(1);
  await shot(rp, "22-admin-replan-before-the-view-loaded");
  await rp.context().close();
  await admin.ctx.dispose();
});

test("a lost answer followed by a different admin plan is never reported as an unchanged route", async ({ browser }) => {
  const { admin, rid } = await plannedRound();
  const { rp, posts } = await openRider(browser, "p2_asha", rid);
  await rp.route(`**/api/rider/rounds/${rid}/reroute`, async (route) => { await route.fetch(); await route.abort("connectionreset"); });
  let holdViews = false, reached = false;
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await rp.route(`**/api/rider/rounds/${rid}/deliveries`, async (route) => { if (holdViews) { reached = true; await gate; } await route.continue(); });
  await openChooser(rp);
  holdViews = true;
  await rp.getByTestId("reroute-start").click();
  await expect.poll(() => reached).toBe(true);                                           // the answer was lost; reading the state is held
  await plan(admin, rid);                                                                 // an admin plan (version 2) replaces the one the request was made on
  release();
  await expect(result(rp)).toContainText("Your admin replanned the round");
  await expect(result(rp)).toContainText("Whether your request reached the server cannot be told");
  await expect(result(rp)).not.toContainText(/unchanged|Nothing was recalculated/);
  await expect(rp.getByTestId("reroute-unresolved")).toHaveCount(0);
  await expect(rp.getByTestId("plan-version")).toContainText("Plan version 2");
  await expect(rp.getByTestId("reroute-open")).toBeEnabled();                             // the state is established, so actions return
  expect(posts).toHaveLength(1);
  await rp.context().close();
  await admin.ctx.dispose();
});
