import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

// Credentials and seeded ids come from the git-ignored state file written by e2e_setup.py.
const state = JSON.parse(readFileSync(process.env.E2E_STATE ?? "", "utf8")) as {
  passwords: Record<string, string>;
  seeded_orders: Record<string, string[]>;
  workbook: string;
};
// Later re-runs point E2E_SHOTS_DIR elsewhere so the accepted Phase 1 screenshots stay as recorded.
const SHOTS = process.env.E2E_SHOTS_DIR
  ? path.resolve(process.env.E2E_SHOTS_DIR)
  : path.resolve(import.meta.dirname, "../../../docs/phase1/screenshots");

async function shot(page: Page, name: string) {
  const project = test.info().project.name;
  await page.screenshot({ path: path.join(SHOTS, `${project}-${name}.png`), fullPage: true });
}

async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(state.passwords[username]);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("sign-in page rejects a wrong password with a generic message", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Username").fill("admin_e2e");
  await page.getByLabel("Password").fill("definitely-wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Wrong username or password");
  await shot(page, "01-login-error");
});

test("admin imports, previews, saves, fixes a pin and edits an order", async ({ page }) => {
  await signIn(page, "admin_e2e");
  await expect(page).toHaveURL(/\/admin$/);

  await page.getByRole("link", { name: "Import" }).click();
  await page.getByLabel("Excel file").setInputFiles(state.workbook);
  await page.getByRole("button", { name: "Upload and preview" }).click();
  const preview = page.getByTestId("preview");
  await expect(preview).toContainText("Orders");
  await expect(preview).toContainText("Excel stored Contact as a number");
  await expect(preview).toContainText("map view centre only");
  await shot(page, "02-import-preview");
  await page.getByRole("button", { name: "Save 3 orders" }).click();

  await expect(page).toHaveURL(/\/admin$/);
  const readiness = page.getByTestId("readiness");
  await expect(readiness).toContainText("1 of 3 orders need a valid pin");
  await expect(page.getByText("Test Customer E3")).toBeVisible();
  await shot(page, "03-orders-blocked");

  // Open the order that needs a pin and set it manually.
  const isMobile = test.info().project.name === "mobile";
  const item = isMobile
    ? page.getByTestId("order-card").filter({ hasText: "Test Customer E3" })
    : page.getByTestId("order-row").filter({ hasText: "Test Customer E3" });
  await item.getByRole("button", { name: "Edit" }).click();
  const editor = page.getByTestId("order-editor");
  await expect(editor).toContainText("Needs a pin");
  await editor.getByLabel(/Set pin manually/).fill("28.6883, 77.2148");
  await editor.getByRole("button", { name: "Save pin" }).click();
  await expect(editor.getByRole("status")).toHaveText("Pin saved.");
  await expect(readiness).toContainText("All 3 orders have a valid pin");

  // Edit status (only the three allowed values are offered).
  const status = editor.getByLabel("Status");
  await expect(status.locator("option")).toHaveText(["Pending", "Postponed", "Completed"]);
  await status.selectOption("Postponed");
  await editor.getByRole("button", { name: "Save details" }).click();
  await expect(editor.getByRole("status")).toHaveText("Saved.");
  await shot(page, "04-order-edited");
});

test("rider sees only own deliveries; other riders' data and admin areas are refused", async ({ page }) => {
  await signIn(page, "rider_a_e2e");
  await expect(page).toHaveURL(/\/rider$/);
  const cards = page.getByTestId("rider-order");
  await expect(cards).toHaveCount(2);
  await expect(page.getByText("Seed Customer A1")).toBeVisible();
  await expect(page.getByText("Seed Customer B3")).toHaveCount(0);
  await shot(page, "05-rider-list");

  // Server-side checks with the rider's real session cookie (not UI hiding).
  const otherRiders = state.seeded_orders["rider_b_e2e"][0];
  const peek = await page.request.get(`/api/rider/orders/${otherRiders}`);
  expect(peek.status()).toBe(404);
  expect(await peek.text()).not.toContain("Seed Customer");
  expect((await page.request.get("/api/admin/rounds")).status()).toBe(403);

  await page.goto("/admin");
  await expect(page).toHaveURL(/\/rider$/); // UI also routes away, but the API refusal above is what protects data
});

test("sign out ends the session on the server", async ({ page }) => {
  await signIn(page, "admin_e2e");
  await expect(page).toHaveURL(/\/admin$/);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/auth/session")).status()).toBe(401);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login$/);
});
