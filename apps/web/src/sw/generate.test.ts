import { describe, expect, it } from "vitest";
import template from "./worker.template.js?raw";
import { renderWorker, shellUrls } from "./generate";

const ID = "0123456789ab";
const URLS = ["/assets/index-DYrsBkym.js", "/assets/index-Drm3DpYN.css", "/icons/icon-192.png", "/index.html", "/manifest.webmanifest"];

describe("which build files the worker may cache", () => {
  it("takes the public shell and nothing else", () => {
    const built = [
      "index.html", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png", "assets/index-DYrsBkym.js", "assets/index-Drm3DpYN.css",
      "sw.js",                  // the worker never caches itself
      "assets/logo.js",         // no content hash in the name
      "assets/index-DYrsBkym.js.map", "icons/icon.svg", "robots.txt", "api/health.json", "private/orders.csv", "../outside.js", "assets/../index.html",
    ];
    expect(shellUrls(built)).toEqual(["/assets/index-DYrsBkym.js", "/assets/index-Drm3DpYN.css", "/icons/icon-192.png", "/icons/icon-512.png", "/index.html", "/manifest.webmanifest"]);
  });

  it("is sorted, so the same build always gives the same list", () => {
    expect(shellUrls(["manifest.webmanifest", "index.html", "assets/b-12345678.js", "assets/a-12345678.js"])).toEqual(
      ["/assets/a-12345678.js", "/assets/b-12345678.js", "/index.html", "/manifest.webmanifest"]);
  });
});

describe("the worker file made from a build", () => {
  it("fills in the build id and the list, and is valid JavaScript", () => {
    const source = renderWorker(template, ID, URLS);
    expect(source).toContain(`const BUILD_ID = "${ID}";`);
    expect(source).toContain(`const PRECACHE = ${JSON.stringify(URLS)};`);
    expect(source).not.toContain("__BUILD_ID__");
    expect(source).not.toContain("__PRECACHE__");
    expect(() => new Function("self", "caches", "fetch", source)).not.toThrow();
  });

  it.each([
    ["a build without index.html", ID, ["/assets/index-DYrsBkym.js"], /index\.html/],
    ["a build without JavaScript", ID, ["/index.html"], /JavaScript/],
    ["an API path", ID, [...URLS, "/api/auth/session"], /API/],
    ["a malformed build id", "not-a-hash", URLS, /build id/],
  ])("refuses %s", (_name, id, urls, message) => {
    expect(() => renderWorker(template, id, urls)).toThrow(message);
  });

  it("refuses a template that lost its placeholders, rather than shipping an empty list", () => {
    expect(() => renderWorker("const BUILD_ID = 'x';", ID, URLS)).toThrow(/placeholders/);
  });
});
