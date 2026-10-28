import { defineConfig, devices } from "@playwright/test";

// Browser tests against the BUILT app served by FastAPI alone (no Vite), exactly as scripts/phone-server.sh serves it:
// one origin, http://localhost:<port>, with FastAPI's own response headers on the HTML document. The Vite-served
// config (playwright.config.ts) never sees those headers. Run: scripts/e2e.sh -c playwright.fastapi.config.ts
const WEB = "http://localhost:8021";
process.env.E2E_WEB = WEB;   // read by e2e/phase2-helpers.ts in the workers

export default defineConfig({
  testDir: "e2e",
  testMatch: "fastapi-*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: WEB, trace: "off", screenshot: "off" },
  projects: [{ name: "mobile", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } }],
  webServer: {
    // Rebuilds the web app first so the test never runs against a stale dist/, then the e2e API factory (recorded matrices).
    command: "npx vite build --logLevel error && ../../services/api/.venv/bin/uvicorn --factory scripts.e2e_app:get_app --app-dir ../../services/api --host 127.0.0.1 --port 8021 --log-level warning",
    url: `${WEB}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { DATABASE_URL: process.env.E2E_DATABASE_URL ?? "", ROUTEWISE_ALLOWED_ORIGINS: WEB, ROUTEWISE_RESOLVE_SHORT_LINKS: "false" },
  },
});
