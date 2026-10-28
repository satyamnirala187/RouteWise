// Runs the REAL worker code (the template rendered exactly as the build renders it) against a fake worker scope and a fake
// CacheStorage. The browser behaviour of the built worker is covered by e2e/fastapi-offline-shell.spec.ts.
import { describe, expect, it, vi } from "vitest";
import template from "./worker.template.js?raw";
import { renderWorker } from "./generate";

const ORIGIN = "https://app.test";
const URLS = ["/assets/index-DYrsBkym.js", "/assets/index-Drm3DpYN.css", "/icons/icon-192.png", "/index.html", "/manifest.webmanifest"];
const TYPE: Record<string, string> = { js: "text/javascript", css: "text/css", png: "image/png", html: "text/html; charset=utf-8", webmanifest: "application/manifest+json" };
const BUILD = "aaaaaaaaaaaa";
const CACHE = `rw-shell-${BUILD}`;

const reply = (path: string, init: ResponseInit = {}) =>
  new Response(`body of ${path}`, { status: 200, headers: { "content-type": TYPE[path.split(".").pop()!] }, ...init });

function fakeCaches() {
  const stores = new Map<string, Map<string, Response>>();
  const open = async (name: string) => {
    const store = stores.get(name) ?? stores.set(name, new Map()).get(name)!;
    return { put: async (key: string, res: Response) => { store.set(key, res); }, keys: async () => [...store.keys()] };
  };
  return {
    stores, open,
    has: async (name: string) => stores.has(name),
    keys: async () => [...stores.keys()],
    delete: async (name: string) => stores.delete(name),
    match: async (key: string, opts?: { cacheName?: string }) => stores.get(opts?.cacheName ?? "")?.get(key)?.clone(),
  };
}

// The worker passes a path while installing and the request itself when the server must answer.
const pathOf = (input: string | { url: string }) => (typeof input === "string" ? input : new URL(input.url).pathname);

function load(opts: { fetchImpl?: (url: string, init?: RequestInit) => Promise<Response>; urls?: string[]; build?: string } = {}) {
  const handlers: Record<string, (e: unknown) => void> = {};
  const caches = fakeCaches();
  const fetchImpl = vi.fn(opts.fetchImpl ?? (async (input: string | { url: string }) => reply(pathOf(input))));
  const scope = {
    location: { origin: ORIGIN }, skipWaiting: vi.fn(), clients: { claim: vi.fn(async () => undefined) },
    addEventListener: (type: string, fn: (e: unknown) => void) => { handlers[type] = fn; },
  };
  const source = renderWorker(template, opts.build ?? BUILD, opts.urls ?? URLS);
  new Function("self", "caches", "fetch", source)(scope, caches, fetchImpl);
  const lifecycle = async (type: "install" | "activate") => {
    const waits: Promise<unknown>[] = [];
    handlers[type]({ waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
  };
  const request = (method: string, url: string, mode = "cors") => {
    let answered: Promise<Response> | undefined;
    handlers.fetch({ request: { method, url, mode }, respondWith: (p: Promise<Response>) => { answered = p; } });
    return answered;
  };
  return { caches, fetchImpl, scope, handlers, lifecycle, request };
}

describe("install", () => {
  it("caches exactly the listed public files, fetched past the HTTP cache, and does not take over by itself", async () => {
    const w = load();
    await w.lifecycle("install");
    expect([...w.caches.stores.get(CACHE)!.keys()].sort()).toEqual(URLS);
    expect(w.fetchImpl.mock.calls.every(([, init]) => (init as RequestInit).cache === "reload")).toBe(true);
    expect(w.scope.skipWaiting).not.toHaveBeenCalled();
  });

  it.each([
    ["a missing file", (url: string) => url.endsWith(".css") ? new Response("nope", { status: 404 }) : reply(url)],
    ["a server error", (url: string) => url.endsWith(".js") ? new Response("boom", { status: 500, headers: { "content-type": "text/plain" } }) : reply(url)],
    ["the app's HTML answered in place of an icon", (url: string) => url.endsWith(".png") ? reply("/index.html") : reply(url)],
    ["an unexpected content type", (url: string) => url.endsWith(".webmanifest") ? new Response("{}", { headers: { "content-type": "text/plain" } }) : reply(url)],
  ])("fails the whole install and leaves no cache behind for %s", async (_name, answer) => {
    const w = load({ fetchImpl: async (url) => answer(url) });
    await expect(w.lifecycle("install")).rejects.toThrow(/cannot precache/);
    expect(w.caches.stores.size).toBe(0);
  });

  it("fails the install, with nothing cached, when the network is down", async () => {
    const w = load({ fetchImpl: async () => { throw new TypeError("Failed to fetch"); } });
    await expect(w.lifecycle("install")).rejects.toThrow("Failed to fetch");
    expect(w.caches.stores.size).toBe(0);
  });
});

describe("activate", () => {
  it("removes older shell caches only, keeps every other cache, and claims open pages", async () => {
    const w = load();
    await w.lifecycle("install");
    for (const name of ["rw-shell-old1", "rw-shell-old2", "some-other-cache", "workbox-precache"]) w.caches.stores.set(name, new Map());
    await w.lifecycle("activate");
    expect([...w.caches.stores.keys()].sort()).toEqual([CACHE, "some-other-cache", "workbox-precache"]);
    expect(w.scope.clients.claim).toHaveBeenCalledOnce();
  });

  it("keeps the older shell when its own cache is missing or incomplete (never leaves the app with nothing)", async () => {
    const missing = load();
    missing.caches.stores.set("rw-shell-old1", new Map());
    await missing.lifecycle("activate");
    expect([...missing.caches.stores.keys()]).toEqual(["rw-shell-old1"]);

    const partial = load();
    partial.caches.stores.set("rw-shell-old1", new Map());
    partial.caches.stores.set(CACHE, new Map([["/index.html", reply("/index.html")]]));
    await partial.lifecycle("activate");
    expect([...partial.caches.stores.keys()].sort()).toEqual([CACHE, "rw-shell-old1"]);
  });
});

describe("what the worker never touches", () => {
  const installed = async () => { const w = load(); await w.lifecycle("install"); w.fetchImpl.mockClear(); return w; };

  it.each([
    ["an API read", "GET", `${ORIGIN}/api/rider/rounds/1/deliveries`, "cors"],
    ["the session check", "GET", `${ORIGIN}/api/auth/session`, "cors"],
    ["sign-in", "POST", `${ORIGIN}/api/auth/login`, "cors"],
    ["a status change", "POST", `${ORIGIN}/api/rider/orders/1/status`, "cors"],
    ["an API call made as a navigation", "GET", `${ORIGIN}/api/auth/session`, "navigate"],
    ["a write to a cached file", "POST", `${ORIGIN}/index.html`, "cors"],
    ["a delete", "DELETE", `${ORIGIN}/assets/index-DYrsBkym.js`, "cors"],
    ["another site", "GET", "https://elsewhere.test/index.html", "cors"],
    ["another site, as a navigation", "GET", "https://elsewhere.test/rider", "navigate"],
    ["a file that is not in the list", "GET", `${ORIGIN}/assets/other-12345678.js`, "cors"],
    ["a listed file with a query string", "GET", `${ORIGIN}/manifest.webmanifest?x=1`, "cors"],
    ["the worker script itself", "GET", `${ORIGIN}/sw.js`, "navigate"],
    ["a file opened as a page", "GET", `${ORIGIN}/assets/other-12345678.js`, "navigate"],
  ])("leaves %s to the network", async (_name, method, url, mode) => {
    const w = await installed();
    expect(w.request(method, url, mode)).toBeUndefined();
    expect(w.fetchImpl).not.toHaveBeenCalled();
  });

  it("never writes to a cache while answering requests", async () => {
    const w = await installed();
    const before = JSON.stringify([...w.caches.stores].map(([k, v]) => [k, [...v.keys()]]));
    for (const [m, u, mode] of [["GET", "/rider", "navigate"], ["GET", "/index.html", "cors"], ["GET", "/api/x", "cors"], ["POST", "/api/x", "cors"]]) {
      const p = w.request(m, ORIGIN + u, mode);
      if (p) await p;
    }
    expect(JSON.stringify([...w.caches.stores].map(([k, v]) => [k, [...v.keys()]]))).toBe(before);
  });
});

describe("what the worker serves", () => {
  it.each(["/", "/index.html", "/login", "/rider", "/rider/rounds/0b6c1c2e", "/admin/plan"])("answers a navigation to %s with the cached shell", async (path) => {
    const w = load();
    await w.lifecycle("install");
    w.fetchImpl.mockClear();
    const res = await w.request("GET", `${ORIGIN}${path}?round=abc`.replace("/index.html?round=abc", "/index.html"), "navigate")!;
    expect(await res.text()).toBe("body of /index.html");
    expect(w.fetchImpl).not.toHaveBeenCalled();   // no network involved
  });

  it("answers each listed file from the cache", async () => {
    const w = load();
    await w.lifecycle("install");
    w.fetchImpl.mockClear();
    for (const path of URLS) expect(await (await w.request("GET", ORIGIN + path)!).text()).toBe(`body of ${path}`);
    expect(w.fetchImpl).not.toHaveBeenCalled();
  });

  it("serves from its own build's cache, never from an older one", async () => {
    const w = load();
    await w.lifecycle("install");
    w.caches.stores.set("rw-shell-old1", new Map([["/index.html", new Response("OLD SHELL")]]));
    expect(await (await w.request("GET", `${ORIGIN}/rider`, "navigate")!).text()).toBe("body of /index.html");
  });

  it("lets the server answer if its cache was emptied behind its back", async () => {
    const w = load();
    await w.lifecycle("install");
    w.caches.stores.delete(CACHE);
    const res = await w.request("GET", `${ORIGIN}/rider`, "navigate")!;
    expect(await res.text()).toBe("body of /rider");   // the fake server's answer to the request itself
    expect(w.fetchImpl).toHaveBeenCalledTimes(URLS.length + 1);   // the install fetches, plus this one
  });
});

describe("taking over", () => {
  it("skips waiting only when the page asks for it", () => {
    const w = load();
    w.handlers.message({ data: { type: "something else" } });
    w.handlers.message({ data: null });
    expect(w.scope.skipWaiting).not.toHaveBeenCalled();
    w.handlers.message({ data: { type: "SKIP_WAITING" } });
    expect(w.scope.skipWaiting).toHaveBeenCalledOnce();
  });
});
