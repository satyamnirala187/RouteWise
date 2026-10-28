import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { shellWorker } from "./vite-plugin-shell.ts";

// Dev: the API runs on 127.0.0.1:8000 and is proxied under /api, so the browser sees a
// single origin (cookies stay SameSite=Lax and first-party; no CORS needed).
export default defineConfig({
  plugins: [react(), tailwindcss(), shellWorker()],  // shellWorker: production builds only (emits sw.js)
  server: {
    host: "localhost",
    port: Number(process.env.WEB_PORT ?? 5173),
    strictPort: true,
    proxy: { "/api": { target: process.env.ROUTEWISE_API_URL ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
});
