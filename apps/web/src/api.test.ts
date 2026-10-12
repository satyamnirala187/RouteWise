import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, loadSession, logout, setCsrfToken } from "./api";

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
