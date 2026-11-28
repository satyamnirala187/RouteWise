import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, isDefiniteRefusal, loadSession, logout, SESSION_CHECK_TIMEOUT_MS, setCsrfToken } from "./api";

type Call = { url: string; init: RequestInit };
let calls: Call[] = [];

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(body === null ? "" : JSON.stringify(body), { status }));
}

beforeEach(() => {
  calls = [];
  setCsrfToken(null);
  vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/auth/session") return respond(200, { username: "a", role: "admin", rider_name: null, csrf_token: "tok-123" });
    return respond(200, { ok: true });
  });
});
afterEach(() => vi.unstubAllGlobals());

const header = (c: Call, name: string) => (c.init.headers as Record<string, string>)[name];

describe("api client", () => {
  it("sends the session CSRF token only on mutating requests", async () => {
    await loadSession();
    await api("/api/admin/rounds");
    await api("/api/admin/orders/1", { method: "PATCH", json: { version: 1 } });
    await api("/api/admin/imports/1", { method: "DELETE" });
    expect(header(calls[1], "X-CSRF-Token")).toBeUndefined();
    expect(header(calls[2], "X-CSRF-Token")).toBe("tok-123");
    expect(header(calls[3], "X-CSRF-Token")).toBe("tok-123");
    expect(header(calls[2], "Content-Type")).toBe("application/json");
  });

  it("uses same-origin credentials and never caches", async () => {
    await api("/api/admin/rounds");
    expect(calls[0].init.credentials).toBe("same-origin");
    expect(calls[0].init.cache).toBe("no-store");
  });

  it("never writes to browser storage", async () => {
    const set = vi.spyOn(Storage.prototype, "setItem");
    await loadSession();
    await logout();
    expect(set).not.toHaveBeenCalled();
  });

  it("forgets the CSRF token on logout", async () => {
    await loadSession();
    await logout();
    await api("/api/admin/orders/1", { method: "PATCH", json: {} });
    expect(header(calls[calls.length - 1], "X-CSRF-Token")).toBeUndefined();
  });

  it("surfaces API errors with status and server message", async () => {
    vi.stubGlobal("fetch", () => respond(409, { detail: "This order changed since you opened it" }));
    await expect(api("/x", { method: "PATCH", json: {} })).rejects.toMatchObject({ status: 409, message: "This order changed since you opened it" });
    vi.stubGlobal("fetch", () => respond(401, { detail: "Not signed in" }));
    expect(await loadSession()).toBeNull();
    vi.stubGlobal("fetch", () => respond(400, { detail: { file_errors: ["Upload an .xlsx workbook."] } }));
    await expect(api("/x", { method: "POST" })).rejects.toBeInstanceOf(ApiError);
  });
});

describe("isDefiniteRefusal", () => {
  it("is true only for a 4xx the API itself wrote", () => {
    expect(isDefiniteRefusal(new ApiError(409, "stale", { code: "STALE_ORDERS", message: "stale", details: [] }))).toBe(true);
    expect(isDefiniteRefusal(new ApiError(422, "invalid", [{ loc: ["body"] }]))).toBe(true);
    expect(isDefiniteRefusal(new ApiError(404, "gone", "Order not found"))).toBe(true);
  });
  it("is false whenever the change may already be committed", () => {
    expect(isDefiniteRefusal(new ApiError(500, "boom", { detail: "x" }))).toBe(false);   // a server error
    expect(isDefiniteRefusal(new ApiError(503, "busy", { code: "BUSY" }))).toBe(false);
    expect(isDefiniteRefusal(new ApiError(408, "timeout", "timeout"))).toBe(false);
    expect(isDefiniteRefusal(new ApiError(409, "no body", undefined))).toBe(false);       // no explanation from the server
    expect(isDefiniteRefusal(new TypeError("Failed to fetch"))).toBe(false);              // no answer at all
    expect(isDefiniteRefusal(new SyntaxError("Unexpected token <"))).toBe(false);         // an unreadable answer
    expect(isDefiniteRefusal(null)).toBe(false);
  });
  it("treats an unreadable body as an unknown outcome, never as a refusal", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("<html>Bad gateway</html>", { status: 502 })));
    const e = await api("/api/admin/rounds/r/stop-groups", { method: "POST", json: {} }).catch((x) => x);
    expect(isDefiniteRefusal(e)).toBe(false);
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("<html>ok?</html>", { status: 200 })));
    expect(isDefiniteRefusal(await api("/api/x").catch((x) => x))).toBe(false);
  });
});

describe("the session check", () => {
  it("returns null only for a server 401", async () => {
    vi.stubGlobal("fetch", () => respond(401, { detail: "Session expired; sign in again" }));
    expect(await loadSession()).toBeNull();
  });

  it.each([
    ["no answer", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a server error", () => respond(500, { detail: "boom" })],
    ["an unreadable answer", () => Promise.resolve(new Response("<html>", { status: 200 }))],
  ])("throws, and does not report a sign-out, for %s", async (_name, answer) => {
    vi.stubGlobal("fetch", answer);
    await expect(loadSession()).rejects.toBeDefined();
  });

  it("keeps the CSRF token when the server cannot be reached", async () => {
    await loadSession();   // the default stub signs in with token tok-123
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));
    await expect(loadSession()).rejects.toBeDefined();
    vi.stubGlobal("fetch", (url: string, init: RequestInit) => { calls.push({ url, init }); return respond(200, {}); });
    await api("/api/admin/orders/1", { method: "PATCH", json: {} });
    expect(header(calls[calls.length - 1], "X-CSRF-Token")).toBe("tok-123");
  });

  it("aborts a hung check after the timeout, and a caller can drop a superseded one", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal("fetch", (_url: string, init: RequestInit) => new Promise((_r, reject) => init.signal!.addEventListener("abort", () => reject(new DOMException("x", "AbortError")))));
      const hung = loadSession();
      const outcome = expect(hung).rejects.toMatchObject({ name: "AbortError" });
      await vi.advanceTimersByTimeAsync(SESSION_CHECK_TIMEOUT_MS);
      await outcome;
      const ac = new AbortController();
      const dropped = expect(loadSession(ac.signal)).rejects.toMatchObject({ name: "AbortError" });
      ac.abort();
      await dropped;
    } finally {
      vi.useRealTimers();
    }
  });
});
