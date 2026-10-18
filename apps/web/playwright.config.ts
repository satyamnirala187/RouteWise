import { defineConfig, devices } from "@playwright/test";

const API = "http://127.0.0.1:8010";
const WEB = "http://localhost:5174";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: WEB, trace: "off", screenshot: "off" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "mobile", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } },
  ],
  webServer: [
    {
      // scripts/e2e_app.py: the real app plus the test-only recorded DU matrices (or the real local
      // Valhalla tiles with ROUTEWISE_E2E_LIVE=1). Never used outside browser tests.
      command: "../../services/api/.venv/bin/uvicorn --factory scripts.e2e_app:get_app --app-dir ../../services/api --host 127.0.0.1 --port 8010 --log-level warning",
      url: `${API}/api/health`,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: process.env.E2E_DATABASE_URL ?? "",
        ROUTEWISE_ALLOWED_ORIGINS: WEB,
        ROUTEWISE_RESOLVE_SHORT_LINKS: "false",
      },
    },
    {
      command: "npx vite --host localhost --port 5174",
      url: WEB,
      reuseExistingServer: false,
      env: { ROUTEWISE_API_URL: API, WEB_PORT: "5174" },
    },
  ],
});
