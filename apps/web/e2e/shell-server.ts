// A FastAPI server that a spec owns: it serves one built web app (a directory) on a free port and can really be
// stopped, so "offline" means a refused connection for the page AND for the service worker's own requests.
// Never the owner's phone server and never the routewise_phone database: it uses the isolated e2e database.
import { spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { emitWorker } from "../vite-plugin-shell.ts";

const API_DIR = path.resolve(process.cwd(), "../../services/api");   // Playwright runs from apps/web
/** The build the Playwright config made for the specs (never apps/web/dist, which the phone server serves). */
export const E2E_DIST = path.resolve(process.cwd(), ".e2e-dist");

export async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.once("error", reject);
    s.listen(0, "127.0.0.1", () => { const { port } = s.address() as { port: number }; s.close(() => resolve(port)); });
  });
}

export function copyBuild(from: string, to: string): string {
  cpSync(from, to, { recursive: true });
  return to;
}

/** A SECOND build for update tests, derived from a finished one: the app's JavaScript changes (so it gets a new content-hashed
 * name, as Vite would give it), index.html points at it, and sw.js is generated again by the real generator from the files that
 * are there. It is not a second Vite run; the first build's files are the only input. */
export function secondBuild(from: string, to: string): string {
  copyBuild(from, to);
  rmSync(path.join(to, "sw.js"));
  const old = readdirSync(path.join(to, "assets")).find((f) => f.endsWith(".js"))!;
  const body = readFileSync(path.join(to, "assets", old), "utf8") + "\n/* second build */\n";
  const next = `index-${createHash("sha256").update(body).digest("base64url").slice(0, 8)}.js`;
  writeFileSync(path.join(to, "assets", next), body);
  rmSync(path.join(to, "assets", old));
  const html = readFileSync(path.join(to, "index.html"), "utf8");
  writeFileSync(path.join(to, "index.html"), html.replace(old, next));
  emitWorker(to);
  return to;
}

export class ShellServer {
  private proc: ChildProcess | null = null;
  private log = "";
  private constructor(readonly port: number) {}

  static async create(): Promise<ShellServer> { return new ShellServer(await freePort()); }

  /** The same origin every time this object starts, so a browser keeps its worker and caches across restarts. */
  get origin() { return `http://localhost:${this.port}`; }

  async start(dist: string): Promise<void> {
    if (this.proc) throw new Error("already running");
    const proc = spawn(path.join(API_DIR, ".venv/bin/uvicorn"),
      ["--factory", "scripts.e2e_shell_app:get_app", "--app-dir", API_DIR, "--host", "127.0.0.1", "--port", String(this.port), "--log-level", "warning"],
      { env: { ...process.env, E2E_WEB_DIST: dist, DATABASE_URL: process.env.E2E_DATABASE_URL ?? "", ROUTEWISE_ALLOWED_ORIGINS: this.origin, ROUTEWISE_RESOLVE_SHORT_LINKS: "false" },
        stdio: ["ignore", "pipe", "pipe"] });
    this.proc = proc;
    proc.stdout!.on("data", (d) => { this.log += d; });
    proc.stderr!.on("data", (d) => { this.log += d; });
    const end = Date.now() + 60_000;
    for (;;) {
      if (proc.exitCode !== null) throw new Error(`server exited early: ${this.log.slice(-800)}`);
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return; } catch { /* not up yet */ }
      if (Date.now() > end) throw new Error(`server did not start: ${this.log.slice(-800)}`);
      await new Promise((r) => setTimeout(r, 150));
    }
  }

  /** Really stops it: the port refuses connections afterwards. */
  async stop(): Promise<void> {
    const proc = this.proc;
    if (!proc) return;
    this.proc = null;
    const done = new Promise<void>((resolve) => proc.once("exit", () => resolve()));
    proc.kill("SIGTERM");
    const t = setTimeout(() => proc.kill("SIGKILL"), 2_000);   // keep-alive connections can hold a graceful stop open
    await done;
    clearTimeout(t);
  }
}
