// Regression for the Android GPS blocker: the built app, served by FastAPI alone, must let its own page use location.
//
// Root cause: FastAPI's HTML responses carried `Permissions-Policy: geolocation=()`, which disables location for the
// document even on http://localhost. The Vite-served browser specs never saw FastAPI's headers, so they could not notice.
//
// MOCKED GEOLOCATION, not real-phone GPS: Playwright grants the permission and emulates a public test point. Nothing here
// replaces navigator.geolocation.getCurrentPosition, so the browser's own policy and permission checks run.
import { expect, test } from "@playwright/test";
import { Api, gotoRound, newPage, signIn, WEB } from "./phase2-helpers";
import { emulateGeolocation, GPS, openChooser, plannedRound, result, viewOf } from "./phase4d-helpers";

test("served by FastAPI, the page may use location and the rider's current-position reroute succeeds (mocked geolocation)", async ({ browser }) => {
  expect(WEB).toBe("http://localhost:8021");   // the FastAPI origin, not Vite
  const { admin, rid } = await plannedRound();
  const rp = await newPage(browser);
  const posts: { status: number; body: string | null }[] = [];
  rp.on("response", (r) => { if (r.request().method() === "POST" && /\/api\/rider\/rounds\/[^/]+\/reroute$/.test(r.url())) posts.push({ status: r.status(), body: r.request().postData() }); });
  await emulateGeolocation(rp, GPS);   // permission granted + emulated public point; getCurrentPosition stays the browser's own

  await signIn(rp, "p2_asha");
  const html = await rp.goto("/rider");   // a deep link: FastAPI answers with index.html
  expect(html!.headers()["permissions-policy"]).toBe("geolocation=(self), camera=(), microphone=()");
  await gotoRound(rp, "/rider", rid);

  const doc = await rp.evaluate(() => {
    const d = document as unknown as { permissionsPolicy?: { allowsFeature(f: string): boolean }; featurePolicy?: { allowsFeature(f: string): boolean } };
    const policy = d.permissionsPolicy ?? d.featurePolicy;
    return {
      supported: !!policy, location: policy?.allowsFeature("geolocation"), camera: policy?.allowsFeature("camera"), microphone: policy?.allowsFeature("microphone"),
      native: /\[native code\]/.test(Function.prototype.toString.call(navigator.geolocation.getCurrentPosition)),
    };
  });
  expect(doc).toEqual({ supported: true, location: true, camera: false, microphone: false, native: true });

  await openChooser(rp);
  await expect(rp.getByTestId("reroute-support")).toHaveCount(0);   // not "blocked", not "insecure"
  await rp.getByTestId("reroute-current").click();
  await expect(result(rp)).toContainText("Route recalculated from your current position (device location)");
  expect(posts).toHaveLength(1);
  expect(posts[0].status).toBe(202);
  expect(JSON.parse(posts[0].body!).origin).toMatchObject({ kind: "current_position" });
  expect((await viewOf(await Api.of(rp), rid)).plan!.rider_route!.revision).toMatchObject({ number: 1, origin_kind: "current_position" });
  await rp.context().close();
  await admin.ctx.dispose();
});
