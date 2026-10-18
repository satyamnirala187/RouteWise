// Shared helpers for the Phase 3 browser specs (3A delivery view, 3B status updates). Customers are
// synthetic; locations are public OSM points; plans use the recorded real-road matrices.
import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { Api, gotoRound, importRound, newPage, signIn, waitRun } from "./phase2-helpers";

/** Screenshots for one step, in their own folder (env override); earlier evidence is never written. */
export function shooter(envVar: string, folder: string) {
  const dir = process.env[envVar] ? path.resolve(process.env[envVar]!) : path.resolve(import.meta.dirname, `../../../docs/phase3/screenshots/${folder}`);
  return async (page: Page, name: string) => {
    mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: path.join(dir, `${test.info().project.name}-${name}.png`), fullPage: true });
  };
}

export type AdminOrder = {
  id: string; order_code: string; version: number; customer_name: string; product: string; contact: string;
  instructions: string | null; status: string; location: { lat: number | null; lng: number | null };
};
type Route = { rider: string; stops: { seq: number; orders: { id: string; order_code: string }[] }[] };

export const orderCard = (page: Page, code: string) => page.locator(`[data-testid=rider-order][data-order="${code}"]`);
export const roundPicker = (page: Page) => page.getByRole("combobox", { name: "Round", exact: true });
export const dirUrl = (lat: number, lng: number) =>
  `https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(6)}%2C${lng.toFixed(6)}&travelmode=two-wheeler`;
export const telUrl = (contact: string) => `tel:${contact.trim().startsWith("+") ? "+" : ""}${contact.replace(/\D/g, "")}`;

export async function ordersOf(admin: Api, rid: string) {
  const list = await admin.json<AdminOrder[]>(`/api/admin/rounds/${rid}/orders`);
  return Object.fromEntries(list.map((o) => [o.order_code, o]));
}
/** Edit an order through the admin API with its current version. */
export async function edit(admin: Api, rid: string, code: string, body: Record<string, unknown>) {
  const o = (await ordersOf(admin, rid))[code];
  return admin.ok("PATCH", `/api/admin/orders/${o.id}`, { version: o.version, ...body });
}

/** Optimize and wait; returns each rider's saved stop order (order codes). */
export async function plan(admin: Api, rid: string): Promise<Record<string, string[]>> {
  const run = await admin.ok<{ id: string }>("POST", `/api/admin/rounds/${rid}/optimize`);
  expect((await waitRun(admin, run.id)).state).toBe("succeeded");
  const p = await admin.json<{ routes: Route[] }>(`/api/admin/rounds/${rid}/plan`);
  return Object.fromEntries(p.routes.map((r) => [r.rider, r.stops.flatMap((s) => s.orders.map((o) => o.order_code))]));
}

export const newRound = (admin: Api) => importRound(admin);

/** Block and count any request to Google from the page: links must never be followed by themselves. */
export async function guardExternal(page: Page) {
  const external: string[] = [];
  await page.context().route(/google\.com|goo\.gl/, (r) => { external.push(r.request().url()); return r.abort(); });
  page.context().on("page", (p) => external.push(`popup:${p.url()}`));
  return external;
}

export async function riderPage(browser: Browser, user: string, rid: string) {
  const rp = await newPage(browser);
  const external = await guardExternal(rp);
  await signIn(rp, user);
  await gotoRound(rp, "/rider", rid);
  await expect(rp.getByTestId("delivery-view")).toHaveAttribute("data-round", rid);
  return { rp, external };
}

export const codesShown = async (loc: Locator) =>
  loc.getByTestId("rider-order").evaluateAll((els) => els.map((e) => e.getAttribute("data-order")));
