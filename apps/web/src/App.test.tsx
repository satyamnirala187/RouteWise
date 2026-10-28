import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { SESSION_CHECK_TIMEOUT_MS, setCsrfToken } from "./api";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
beforeEach(() => setCsrfToken(null));

const json = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const calls: string[] = [];
const stub = (impl: (url: string, init?: RequestInit) => Promise<Response>) => {
  calls.length = 0;
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => { calls.push(url); return impl(url, init); });
};
const mount = () => render(<MemoryRouter initialEntries={["/rider"]}><App /></MemoryRouter>);
const connectScreen = () => screen.findByRole("heading", { name: "Connect to load your deliveries" });
const notSignedOutShown = () => expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();

describe("starting the app", () => {
  it("shows the sign-in page only when the server says 401", async () => {
    stub(() => json(401, { detail: "Not signed in" }));
    mount();
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByTestId("connect-screen")).toBeNull();
  });

  it.each([
    ["no connection (the request fails)", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a server error", () => json(500, { detail: "boom" })],
    ["a bad gateway page that is not JSON", () => Promise.resolve(new Response("<html>502</html>", { status: 200 }))],
    ["a 503 while the server restarts", () => json(503, { detail: "unavailable" })],
  ])("shows 'Connect to load your deliveries' for %s, and does not treat it as a sign-out", async (_name, answer) => {
    stub(answer);
    mount();
    await connectScreen();
    expect(screen.getByText(/You have not been signed out/)).toBeTruthy();
    expect(screen.getByText(/not saved on this device/)).toBeTruthy();   // no claim that deliveries are available offline
    notSignedOutShown();
    expect(calls).toEqual(["/api/auth/session"]);   // nothing else was asked, in particular no logout
  });

  it("gives up on a hung session check after the timeout and says it could not connect", async () => {
    vi.useFakeTimers();
    stub((_url, init) => new Promise((_resolve, reject) => init!.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))));
    mount();
    expect(screen.queryByTestId("connect-screen")).toBeNull();   // still checking
    await act(async () => { await vi.advanceTimersByTimeAsync(SESSION_CHECK_TIMEOUT_MS); });
    expect(screen.getByTestId("connect-screen")).toBeTruthy();
    notSignedOutShown();
  });

  it("'Try again' asks the server again, and a real 401 then shows the sign-in page", async () => {
    let n = 0;
    stub(() => (n++ === 0 ? Promise.reject(new TypeError("Failed to fetch")) : json(401, { detail: "Session expired; sign in again" })));
    mount();
    await connectScreen();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByTestId("connect-screen")).toBeNull();
    expect(calls).toEqual(["/api/auth/session", "/api/auth/session"]);
  });

  it("looks again by itself when the connection returns", async () => {
    let n = 0;
    stub(() => (n++ === 0 ? Promise.reject(new TypeError("Failed to fetch")) : json(401, { detail: "Not signed in" })));
    mount();
    await connectScreen();
    act(() => { window.dispatchEvent(new Event("online")); });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
  });
});
