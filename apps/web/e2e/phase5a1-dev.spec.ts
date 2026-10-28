/// <reference lib="dom" />
// 5A-1: the Vite development server is unchanged: it never registers the shell worker (production builds only).
import { expect, test } from "@playwright/test";

test("the Vite dev server serves the app without registering a service worker", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  const worker = await page.evaluate(async () => ({ registrations: (await navigator.serviceWorker.getRegistrations()).length, controlled: !!navigator.serviceWorker.controller }));
  expect(worker).toEqual({ registrations: 0, controlled: false });
});
