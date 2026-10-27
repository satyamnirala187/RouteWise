/// <reference lib="dom" />  // page.evaluate() bodies run in the browser
// Shared helpers for the Phase 2 (step 2C) browser specs. All customers are synthetic and every
// location is a public OpenStreetMap point from tests/fixtures/public_locations_du_north.json.
import { expect, request as playwrightRequest, test, type APIRequestContext, type Browser, type Locator, type Page } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

export const WEB = process.env.E2E_WEB ?? "http://localhost:5174";   // E2E_WEB: playwright.fastapi.config.ts serves the app from FastAPI

type Point = { lat: number; lng: number };
export const state = JSON.parse(readFileSync(process.env.E2E_STATE ?? "", "utf8")) as {
  passwords: Record<string, string>;
  phase2: { workbook: string; orders: number; places: Record<string, Point>; riders: Record<string, string>; hold_file: string };
};
export const P = state.phase2.places;
export const coords = (p: Point) => `${p.lat}, ${p.lng}`;
/** Strings that must never reach an admin: the riders' Home/Custom points. */
export const PRIVATE_STRINGS = [String(P.home_r1.lat), String(P.home_r1.lng), String(P.custom_r2.lat), String(P.custom_r2.lng)];

// New evidence only: the accepted Phase 1 / 2A screenshots are never written by this spec.
const SHOTS = process.env.E2E_2C_SHOTS_DIR
  ? path.resolve(process.env.E2E_2C_SHOTS_DIR)
  : path.resolve(import.meta.dirname, "../../../docs/phase2/screenshots/2c");

export async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  const project = test.info().project.name;
  await page.screenshot({ path: path.join(SHOTS, `${project}-${name}.png`), fullPage: true });
}

/** Screenshot of one element (e.g. a rider's card for this round, not every round they are in). */
export async function shotOf(locator: Locator, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await locator.screenshot({ path: path.join(SHOTS, `${test.info().project.name}-${name}.png`) });
}

export const isMobile = () => test.info().project.name === "mobile";

/** A page with the current project's viewport (desktop 1280 px or mobile 390 px). */
export async function newPage(browser: Browser): Promise<Page> {
  const use = test.info().project.use;
  const context = await browser.newContext({
    baseURL: WEB, viewport: use.viewport, isMobile: use.isMobile, hasTouch: use.hasTouch, deviceScaleFactor: use.deviceScaleFactor,
  });
  return context.newPage();
}

export async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(state.passwords[username]);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}

/** A signed-in API session (cookie + CSRF), used to arrange state quickly. */
export class Api {
  private constructor(public ctx: APIRequestContext, readonly csrf: string) {}

  static async login(username: string): Promise<Api> {
    const ctx = await playwrightRequest.newContext({ baseURL: WEB, extraHTTPHeaders: { Origin: WEB } });
    const r = await ctx.post("/api/auth/login", { data: { username, password: state.passwords[username] } });
    expect(r.status()).toBe(200);
    const s = await (await ctx.get("/api/auth/session")).json();
    return new Api(ctx, s.csrf_token);
  }

  /** The API session of a signed-in page (same cookie as the browser). */
  static async of(page: Page): Promise<Api> {
    const s = await (await page.request.get("/api/auth/session")).json();
    return new Api(page.request, s.csrf_token);
  }

  get(url: string) { return this.ctx.get(url); }
  async json<T = unknown>(url: string): Promise<T> {
    const r = await this.ctx.get(url);
    expect(r.ok(), `${url} → ${r.status()}`).toBeTruthy();
    return r.json();
  }
  send(method: string, url: string, data?: unknown) {
    return this.ctx.fetch(url, { method, data, headers: { "X-CSRF-Token": this.csrf, Origin: WEB } });
  }
  async ok<T = unknown>(method: string, url: string, data?: unknown): Promise<T> {
    const r = await this.send(method, url, data);
    expect(r.ok(), `${method} ${url} → ${r.status()} ${await r.text()}`).toBeTruthy();
    return r.json();
  }
}

export async function ensureDepots(admin: Api) {
  const depots = await admin.json<Record<string, { version: number; lat: number; lng: number } | null>>("/api/admin/depots");
  for (const kind of ["office", "warehouse"] as const) {
    const d = depots[kind];
    const p = P[kind];
    if (!d) await admin.ok("PUT", `/api/admin/depots/${kind}`, { version: null, label: kind === "office" ? "Office" : "Warehouse", ...p });
    else if (d.lat !== p.lat || d.lng !== p.lng) await admin.ok("PUT", `/api/admin/depots/${kind}`, { version: d.version, label: kind === "office" ? "Office" : "Warehouse", ...p });
  }
}

/** Import the Phase 2 workbook through the real import API; returns the new round id. */
export async function importRound(admin: Api): Promise<string> {
  const r = await admin.ctx.fetch("/api/admin/imports", {
    method: "POST", headers: { "X-CSRF-Token": admin.csrf, Origin: WEB },
    multipart: { file: { name: "e2e-phase2-orders.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: readFileSync(state.phase2.workbook) } },
  });
  expect(r.status()).toBe(201);
  const preview = await r.json();
  const committed = await admin.ok<{ round_id: string }>("POST", `/api/admin/imports/${preview.id}/commit`);
  return committed.round_id;
}

export async function riderIds(admin: Api): Promise<Record<string, string>> {
  const list = await admin.json<{ id: string; username: string }[]>("/api/admin/riders");
  return Object.fromEntries(list.map((r) => [r.username, r.id]));
}

export type Spec = { user: string; vehicle: "scooter" | "bike"; capacity: number; start: "office" | "warehouse"; kind: string; at?: Point };

/** Add riders to a round, choose their destinations as them, and confirm as them. */
export async function prepareRound(admin: Api, rid: string, specs: Spec[], { confirm = true } = {}) {
  const ids = await riderIds(admin);
  for (const s of specs) {
    await admin.ok("PUT", `/api/admin/rounds/${rid}/riders/${ids[s.user]}`, { vehicle: s.vehicle, capacity: s.capacity, start: s.start });
    const rider = await Api.login(s.user);
    await rider.ok("PUT", `/api/rider/rounds/${rid}/destination`, s.at ? { kind: s.kind, ...s.at } : { kind: s.kind });
    if (confirm) {
      const setup = await rider.json<{ config_version: number }>(`/api/rider/rounds/${rid}`);
      await rider.ok("POST", `/api/rider/rounds/${rid}/confirm`, { config_version: setup.config_version });
    }
    await rider.ctx.dispose();
  }
  return ids;
}

export async function waitRun(admin: Api, runId: string) {
  for (let i = 0; i < 300; i++) {
    const r = await admin.json<{ state: string }>(`/api/admin/planning-runs/${runId}`);
    if (["succeeded", "failed", "stale", "interrupted"].includes(r.state)) return r;
    await new Promise((res) => setTimeout(res, 200));
  }
  throw new Error("run did not finish");
}

export function hold(on: boolean) {
  const f = state.phase2.hold_file;
  if (on) { mkdirSync(path.dirname(f), { recursive: true }); writeFileSync(f, "hold"); }
  else if (existsSync(f)) rmSync(f);
}

/** No customer or endpoint data in localStorage, sessionStorage or IndexedDB. */
export async function expectNoBrowserStorage(page: Page) {
  const stored = await page.evaluate(async () => ({
    local: localStorage.length, session: sessionStorage.length,
    idb: typeof indexedDB.databases === "function" ? (await indexedDB.databases()).length : 0,
  }));
  expect(stored).toEqual({ local: 0, session: 0, idb: 0 });
}

/** No horizontal page overflow at the current width. */
export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

export async function gotoRound(page: Page, path: string, rid: string) {
  await page.goto(`${path}?round=${rid}`);
}
