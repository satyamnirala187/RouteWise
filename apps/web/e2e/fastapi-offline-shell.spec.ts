/// <reference lib="dom" />
// Step 5A-1: the offline APP SHELL, in Chromium, against the BUILT app served by FastAPI alone, on a server the spec starts and
// STOPS itself (e2e/shell-server.ts): "offline" is a refused connection for the page and for the worker, not an emulation.
// Public shell only: no rider snapshot, no IndexedDB, no queue. Nothing here claims deliveries are available offline; the
// connect screen says they are not. Isolated e2e database (routewise_e2e) only; never the phone server or routewise_phone.
import { expect, test, type BrowserContext, type Page, type TestInfo } from "@playwright/test";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { expectNoBrowserStorage, state } from "./phase2-helpers";
import { copyBuild, E2E_DIST, secondBuild, ShellServer } from "./shell-server";

const POLICY = "geolocation=(self), camera=(), microphone=()";
const SHELL_PREFIX = "rw-shell-";

const diskFiles = (dir: string): string[] =>
  readdirSync(dir, { recursive: true, withFileTypes: true }).filter((e) => e.isFile())
    .map((e) => path.relative(dir, path.join(e.parentPath, e.name)).split(path.sep).join("/"));
const workerId = (dist: string) => /const BUILD_ID = "([0-9a-f]{12})"/.exec(readFileSync(path.join(dist, "sw.js"), "utf8"))![1];
const jsAsset = (dist: string) => readdirSync(path.join(dist, "assets")).find((f) => f.endsWith(".js"))!;
const sha = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");

const cacheKeys = (page: Page) => page.evaluate(() => caches.keys().then((k) => k.sort()));
// Tolerates a navigation in progress, so it can be polled while a page reloads.
const loadedScripts = (page: Page) => page.evaluate(() => Array.from(document.scripts).map((s) => new URL(s.src).pathname)).catch(() => [] as string[]);
const controlled = (page: Page) => page.evaluate(() => !!navigator.serviceWorker.controller);

/** First visit online: the worker installs, activates and takes control of the page. */
async function install(page: Page, origin: string, route = "/login") {
  await page.goto(origin + route);
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await expect.poll(() => controlled(page)).toBe(true);
}

/** Records Content-Security-Policy violations of the page (none are expected: the worker is allowed by the current policy). */
async function watchCsp(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  return () => page.evaluate(() => (window as unknown as { __csp: string[] }).__csp);
}

async function signInAt(page: Page, origin: string, username: string) {
  await page.goto(origin + "/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(state.passwords[username]);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("link", { name: "My deliveries" })).toBeVisible();
}

const connectScreen = (page: Page) => page.getByRole("heading", { name: "Connect to load your deliveries" });

async function run(browser: import("@playwright/test").Browser, body: (server: ShellServer, ctx: BrowserContext) => Promise<void>, dist = E2E_DIST) {
  const server = await ShellServer.create();
  await server.start(dist);
  const ctx = await browser.newContext({ serviceWorkers: "allow" });
  try { await body(server, ctx); } finally { await ctx.close(); await server.stop(); }
}

test("the worker installs on localhost under the current CSP, and its cache is exactly the build's public files", async ({ browser }) => {
  await run(browser, async (server, ctx) => {
    const page = await ctx.newPage();
    const csp = await watchCsp(page);
    const errors: string[] = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await install(page, server.origin);

    const name = SHELL_PREFIX + workerId(E2E_DIST);
    expect(await cacheKeys(page)).toEqual([name]);
    const expected = diskFiles(E2E_DIST).filter((f) => f !== "sw.js").map((f) => `/${f}`).sort();   // independent of the generator's rules
    expect(expected.length).toBeGreaterThanOrEqual(6);
    const cached = await page.evaluate(async (n) => {
      const c = await caches.open(n);
      return Promise.all((await c.keys()).map(async (r) => {
        const res = (await c.match(r))!;
        const digest = await crypto.subtle.digest("SHA-256", await res.arrayBuffer());
        return { path: new URL(r.url).pathname, type: res.headers.get("content-type"), status: res.status, sha: Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("") };
      }));
    }, name);
    expect(cached.map((c) => c.path).sort()).toEqual(expected);
    for (const c of cached) {   // byte-identical to the public file on disk; nothing else can be in the cache
      expect(c.sha, c.path).toBe(sha(readFileSync(path.join(E2E_DIST, c.path))));
      expect(c.status).toBe(200);
    }
    expect(Object.fromEntries(cached.map((c) => [c.path.split(".").pop(), c.type!.split(";")[0]]))).toMatchObject(
      { html: "text/html", webmanifest: "application/manifest+json", png: "image/png", css: "text/css" });

    // Served as intended: the worker is JavaScript at the root and revalidated; only hashed assets are immutable.
    const get = (p: string) => page.request.get(server.origin + p);
    const worker = await get("/sw.js");
    expect(worker.headers()["content-type"]).toMatch(/javascript/);
    expect(worker.headers()["cache-control"]).toBe("no-cache");
    for (const p of ["/index.html", "/manifest.webmanifest", "/icons/icon-192.png"]) expect((await get(p)).headers()["cache-control"], p).toBe("no-cache");
    expect((await get(`/assets/${jsAsset(E2E_DIST)}`)).headers()["cache-control"]).toBe("public, max-age=31536000, immutable");
    expect((await get("/api/health")).headers()["cache-control"]).toBe("no-store");
    expect(await page.locator('link[rel="manifest"]').getAttribute("href")).toBe("/manifest.webmanifest");

    expect(await csp()).toEqual([]);
    expect(errors.filter((e) => !/status of 401/.test(e))).toEqual([]);   // the signed-out session check legitimately answers 401
  });
});

test("after installation, reloading and deep links with the server STOPPED show the app, not Chrome's offline page", async ({ browser }) => {
  await run(browser, async (server, ctx) => {
    const page = await ctx.newPage();
    const csp = await watchCsp(page);
    await install(page, server.origin);
    await server.stop();   // from here every request to the server is refused, including the worker's own

    for (const route of ["/login", "/rider", "/rider?round=abc", "/rider/rounds/0b6c1c2e-0000-4000-8000-000000000000", "/admin/plan", "/no/such/page", "/"]) {
      const response = await page.goto(server.origin + route);
      expect(response!.fromServiceWorker(), route).toBe(true);
      expect(page.url().startsWith(server.origin), route).toBe(true);   // not chrome-error://
      expect(await page.title(), route).toBe("RouteWise");
      await expect(connectScreen(page), route).toBeVisible();
      await expect(page.getByRole("button", { name: "Sign in" }), route).toHaveCount(0);   // an unreachable server is not a sign-out
    }
    await page.reload();   // the case observed on the phone: refresh while offline
    await expect(connectScreen(page)).toBeVisible();

    // The document served from the cache still carries the security headers the server gave it, and the page honours them.
    const doc = await page.goto(server.origin + "/rider");
    expect(doc!.headers()["permissions-policy"]).toBe(POLICY);
    expect(doc!.headers()["content-security-policy"]).toContain("default-src 'self'");
    expect(await page.evaluate(() => {
      const d = document as unknown as { permissionsPolicy?: { allowsFeature(f: string): boolean }; featurePolicy?: { allowsFeature(f: string): boolean } };
      const policy = d.permissionsPolicy ?? d.featurePolicy;
      return { geolocation: policy?.allowsFeature("geolocation"), camera: policy?.allowsFeature("camera") };
    })).toEqual({ geolocation: true, camera: false });
    expect(await csp()).toEqual([]);
  });
});

test("first-ever offline access cannot work: nothing was installed yet (documented limit)", async ({ browser }) => {
  const server = await ShellServer.create();   // never started: the origin refuses connections
  const ctx = await browser.newContext();
  try {
    const page = await ctx.newPage();
    await expect(page.goto(server.origin + "/rider")).rejects.toThrow(/ERR_CONNECTION_REFUSED/);
    expect(page.url()).not.toContain("/rider");   // Chrome's own error page, not the app
  } finally { await ctx.close(); }
});

test("an unreachable server at startup is not a sign-out; a real 401 is", async ({ browser }) => {
  await run(browser, async (server, ctx) => {
    const page = await ctx.newPage();
    await install(page, server.origin);
    await signInAt(page, server.origin, "rider_a_e2e");
    const before = (await ctx.cookies()).find((c) => c.name === "rw_session")!;

    await server.stop();
    await page.reload();
    await expect(connectScreen(page)).toBeVisible();
    await expect(page.getByText(/You have not been signed out/)).toBeVisible();
    await expect(page.getByText(/not saved on this device/)).toBeVisible();   // and no claim that deliveries are available offline
    await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);
    expect((await ctx.cookies()).find((c) => c.name === "rw_session")?.value).toBe(before.value);   // the session was left alone

    await server.start(E2E_DIST);   // same origin again
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("link", { name: "My deliveries" })).toBeVisible();   // still signed in

    await ctx.clearCookies();   // the server now answers 401 "Not signed in"
    await page.reload();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await expect(page.getByTestId("connect-screen")).toHaveCount(0);
  });
});

test("the worker never intercepts or caches the API; with customer data on screen the cache holds public shell files only", async ({ browser }) => {
  await run(browser, async (server, ctx) => {
    const page = await ctx.newPage();
    await install(page, server.origin);   // the worker controls the page BEFORE any API call below
    const api: { method: string; path: string; fromWorker: boolean }[] = [];
    page.on("response", (r) => {
      const u = new URL(r.url());
      if (u.pathname.startsWith("/api/")) api.push({ method: r.request().method(), path: u.pathname, fromWorker: r.fromServiceWorker() });
    });
    await signInAt(page, server.origin, "rider_a_e2e");   // POST /api/auth/login and the session check
    const names = await page.request.get(server.origin + "/api/rider/orders");
    const orders = await names.json() as { customer_name: string }[];
    const csrf = (await (await page.request.get(server.origin + "/api/auth/session")).json() as { csrf_token: string }).csrf_token;
    expect(orders.length).toBeGreaterThan(0);                       // customer data exists in API answers...
    await page.reload();                                           // ...and a controlled page loads and shows the rider's screen
    await expect(page.getByRole("link", { name: "My deliveries" })).toBeVisible();
    await expect(page.getByText(/Seed Customer/).first()).toBeVisible();
    expect(await controlled(page)).toBe(true);
    await expectNoBrowserStorage(page);                            // nothing in local/session storage or IndexedDB
    await page.getByRole("button", { name: "Sign out" }).click();  // POST /api/auth/logout
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

    expect(api.length).toBeGreaterThanOrEqual(6);
    expect(api.some((a) => a.method === "POST" && a.path === "/api/auth/login")).toBe(true);
    expect(api.some((a) => a.method === "POST" && a.path === "/api/auth/logout")).toBe(true);
    expect(api.filter((a) => a.fromWorker)).toEqual([]);           // no API request or answer ever came from the worker

    const name = SHELL_PREFIX + workerId(E2E_DIST);
    expect(await cacheKeys(page)).toEqual([name]);
    const leaks = await page.evaluate(async ({ n, needles }) => {
      const c = await caches.open(n);
      const found: string[] = [];
      for (const r of await c.keys()) {
        const text = await (await c.match(r))!.clone().text();
        for (const needle of needles) if (text.includes(needle)) found.push(`${new URL(r.url).pathname}: ${needle.slice(0, 6)}…`);
        if (new URL(r.url).pathname.startsWith("/api/")) found.push("API URL " + r.url);
      }
      return found;
    }, { n: name, needles: [orders[0].customer_name, csrf, "rider_a_e2e", state.passwords.rider_a_e2e] });   // the values, not field names that appear in the app's code
    expect(leaks).toEqual([]);
  });
});

test("a failed precache (a listed file the server does not have) installs nothing, caches nothing and leaves the app working", async ({ browser }, testInfo: TestInfo) => {
  const broken = copyBuild(E2E_DIST, testInfo.outputPath("broken-build"));
  rmSync(path.join(broken, "icons", "icon-512.png"));   // sw.js still lists it; the server answers the SPA fallback (HTML, 200) for it
  await run(browser, async (server, ctx) => {
    const page = await ctx.newPage();
    await page.goto(server.origin + "/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();   // the app itself is fine
    await expect.poll(() => page.evaluate(async () => {
      const r = await navigator.serviceWorker.getRegistration();
      return !r || (!r.installing && !r.waiting && !r.active);
    }), { timeout: 15_000 }).toBe(true);
    expect(await cacheKeys(page)).toEqual([]);   // the half-filled cache was removed, so nothing can ever be served from it
    expect(await controlled(page)).toBe(false);
    await server.stop();
    await expect(page.goto(server.origin + "/login")).rejects.toThrow(/ERR_CONNECTION_REFUSED/);   // no worker, so offline really is offline
  }, broken);
});

async function twoBuilds(testInfo: TestInfo) {
  const v1 = copyBuild(E2E_DIST, testInfo.outputPath("build-1"));
  const v2 = secondBuild(E2E_DIST, testInfo.outputPath("build-2"));
  expect(workerId(v1)).not.toBe(workerId(v2));
  expect(jsAsset(v1)).not.toBe(jsAsset(v2));
  return { v1, v2, id1: workerId(v1), id2: workerId(v2), js1: jsAsset(v1), js2: jsAsset(v2) };
}

/** Build 1 is installed in tab A, then build 2 is deployed on the same origin and installs in the background while tab B opens. */
async function updateWaiting(server: ShellServer, ctx: BrowserContext, v2: string, ids: { id1: string; id2: string; js1: string }) {
  const tabA = await ctx.newPage();
  await install(tabA, server.origin);
  await tabA.evaluate(() => { (window as unknown as { __tabA: string }).__tabA = "the first page, never reloaded"; return caches.open("someone-elses-cache"); });
  expect(await cacheKeys(tabA)).toEqual([`${SHELL_PREFIX}${ids.id1}`, "someone-elses-cache"].sort());
  expect(await loadedScripts(tabA)).toContain(`/assets/${ids.js1}`);
  await server.stop();
  await server.start(v2);   // the deployment of build 2
  const tabB = await ctx.newPage();
  await tabB.goto(server.origin + "/login");
  expect(await loadedScripts(tabB)).toContain(`/assets/${ids.js1}`);   // cache-first: an update never swaps the shell under a page
  await expect.poll(() => cacheKeys(tabB), { timeout: 20_000 }).toContain(`${SHELL_PREFIX}${ids.id2}`);   // build 2 installed in the background...
  expect(await cacheKeys(tabB)).toContain(`${SHELL_PREFIX}${ids.id1}`);                                    // ...next to build 1, which still serves
  return { tabA, tabB };
}

test("two builds: an older open tab keeps working while the update waits; obsolete shell caches go safely; nothing reloads by itself", async ({ browser }, testInfo: TestInfo) => {
  test.setTimeout(120_000);
  const { v1, v2, id1, id2, js1, js2 } = await twoBuilds(testInfo);
  await run(browser, async (server, ctx) => {
    const { tabA, tabB } = await updateWaiting(server, ctx, v2, { id1, id2, js1 });
    await expect(tabA.getByTestId("shell-update")).toContainText("next time you open the app");
    await expect(tabB.getByTestId("shell-update")).toBeVisible();

    // While the update waits, the older tab is fully functional: its own JavaScript runs, and it signs in through the API.
    await tabA.getByLabel("Username").fill("rider_a_e2e");
    await tabA.getByLabel("Password").fill(state.passwords.rider_a_e2e);
    await tabA.getByRole("button", { name: "Sign in" }).click();
    await expect(tabA.getByRole("link", { name: "My deliveries" })).toBeVisible();
    expect(await tabA.evaluate(() => (window as unknown as { __tabA: string }).__tabA)).toBe("the first page, never reloaded");
    expect(await cacheKeys(tabB)).toContain(`${SHELL_PREFIX}${id1}`);   // build 1 is still there: build 2 has not taken over

    // The rider updates in tab B: it reloads on build 2, and build 1's shell cache is removed. Unrelated caches are not touched.
    // Failure-only diagnostics: this step once timed out without a recorded cause (see the 5A-1 report); a recurrence will say why.
    const diag = (tab: Page) => tab.evaluate(async () => {
      const r = await navigator.serviceWorker.getRegistration();
      return { waiting: r?.waiting?.state ?? null, installing: r?.installing?.state ?? null, active: r?.active?.state ?? null,
        controller: navigator.serviceWorker.controller?.state ?? null, caches: await caches.keys(), banner: !!document.querySelector('[data-testid="shell-update"]') };
    }).catch((e) => String(e));
    const navs: string[] = [];
    tabB.on("framenavigated", (f) => navs.push(f.url()));
    const before = await diag(tabB);
    await tabB.getByRole("button", { name: "Reload to update" }).click();
    try { await expect.poll(() => loadedScripts(tabB), { timeout: 15_000 }).toContain(`/assets/${js2}`); } catch (e) {
      console.log("DIAG FAIL before", JSON.stringify(before), "after", JSON.stringify(await diag(tabB)), "navs", JSON.stringify(navs), "scripts", JSON.stringify(await loadedScripts(tabB)));
      throw e;
    }
    expect(await loadedScripts(tabB)).not.toContain(`/assets/${js1}`);
    await expect.poll(() => cacheKeys(tabB), { timeout: 15_000 }).toEqual([`${SHELL_PREFIX}${id2}`, "someone-elses-cache"].sort());

    // Tab A, still on build 1, was not reloaded or logged out behind the rider's back, and still works; it is only OFFERED a reload.
    expect(await tabA.evaluate(() => (window as unknown as { __tabA: string }).__tabA)).toBe("the first page, never reloaded");
    await expect(tabA.getByRole("link", { name: "My deliveries" })).toBeVisible();
    await expect(tabA.getByTestId("shell-update")).toBeVisible();
    await tabA.getByRole("button", { name: "Sign out" }).click();   // an API call from the old page still works
    await expect(tabA.getByRole("button", { name: "Sign in" })).toBeVisible();
    await tabA.getByRole("button", { name: "Reload to update" }).click();
    await expect.poll(() => loadedScripts(tabA), { timeout: 15_000 }).toContain(`/assets/${js2}`);

    // And build 2 is what loads offline.
    await server.stop();
    const offline = await tabA.goto(server.origin + "/rider");
    expect(offline!.fromServiceWorker()).toBe(true);
    expect(await loadedScripts(tabA)).toContain(`/assets/${js2}`);
    await expect(connectScreen(tabA)).toBeVisible();
  }, v1);
});

test("two builds: with no tab left open, the waiting build takes over (next launch)", async ({ browser }, testInfo: TestInfo) => {
  test.setTimeout(120_000);
  const { v1, v2, id1, id2, js1, js2 } = await twoBuilds(testInfo);
  await run(browser, async (server, ctx) => {
    const { tabA, tabB } = await updateWaiting(server, ctx, v2, { id1, id2, js1 });
    await tabA.close();
    await tabB.close();   // no page of the origin is left: the browser may now activate the waiting build
    await expect.poll(async () => {
      const probe = await ctx.newPage();   // look, then leave again, so the build can take over between looks
      await probe.goto(server.origin + "/login");
      const keys = await cacheKeys(probe);
      await probe.close();
      return keys;
    }, { timeout: 30_000, intervals: [1_500] }).toEqual([`${SHELL_PREFIX}${id2}`, "someone-elses-cache"].sort());
    const launch = await ctx.newPage();
    await launch.goto(server.origin + "/login");
    expect(await loadedScripts(launch)).toContain(`/assets/${js2}`);
  }, v1);
});
