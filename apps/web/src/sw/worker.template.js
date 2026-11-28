// RouteWise app-shell service worker (step 5A-1). This file is a TEMPLATE: vite-plugin-shell.ts fills in BUILD_ID and
// PRECACHE from the files the build actually wrote (src/sw/generate.ts) and emits the result as /sw.js.
//
// It caches ONLY the public shell: index.html, content-hashed JS/CSS, the manifest and the icons. It never touches /api/
// (sessions, customer data, mutations) or anything cross-origin, and it keeps no data of its own.
const BUILD_ID = "__BUILD_ID__";
const PRECACHE = __PRECACHE__;
const PREFIX = "rw-shell-";
const CACHE = PREFIX + BUILD_ID;
const SHELL = "/index.html";
const SHELL_PATHS = new Set(PRECACHE);
// What each precached file must be. A file the server does not have is answered with the SPA fallback (HTML, 200),
// which must never be stored as that file.
const TYPES = { html: "text/html", js: "javascript", css: "text/css", webmanifest: "json", png: "image/png" };

self.addEventListener("install", (event) => {
  // No skipWaiting here: a new build waits until the rider's tabs are closed or they choose "Reload to update".
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE);
      await Promise.all(PRECACHE.map(async (path) => {
        const res = await fetch(path, { cache: "reload" });
        const want = TYPES[path.slice(path.lastIndexOf(".") + 1)];
        if (!res.ok || res.redirected || !want || !(res.headers.get("content-type") || "").includes(want)) {
          throw new Error("cannot precache " + path);
        }
        await cache.put(path, res);
      }));
    } catch (e) {
      await caches.delete(CACHE); // a half-filled cache is never used; the previous worker stays in charge
      throw e;
    }
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // Older shell caches go only once this build's own cache is complete, and nothing but rw-shell-* caches is touched.
    if (await caches.has(CACHE) && (await (await caches.open(CACHE)).keys()).length === PRECACHE.length) {
      for (const name of await caches.keys()) if (name.startsWith(PREFIX) && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

// A route of the app (/, /rider, /rider/…) has no file extension; /sw.js, /assets/x.js and the like are files.
const isAppRoute = (path) => path === "/index.html" || !path.slice(path.lastIndexOf("/") + 1).includes(".");

async function fromShell(path, request) {
  const hit = await caches.match(path, { cacheName: CACHE });
  return hit || fetch(request || path); // cache emptied behind our back: let the server answer
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; // mutations are never touched
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return; // other sites and every API call
  if (request.mode === "navigate" && isAppRoute(url.pathname)) event.respondWith(fromShell(SHELL, request));
  else if (!url.search && SHELL_PATHS.has(url.pathname)) event.respondWith(fromShell(url.pathname, request));
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});
