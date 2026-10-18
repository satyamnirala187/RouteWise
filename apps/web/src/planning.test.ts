import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type PlanningRun, type RunState } from "./api";
import { FIX, isTerminal, km, pollRun, provenanceLabel, trafficFree } from "./planning";

const run = (state: RunState): PlanningRun => ({
  id: "r1", round_id: "x", state, mode: "smart", input_version: 1, requested_at: "2026-10-18T10:00:00Z",
  started_at: null, finished_at: null, error: null, plan_version: null, timings: null,
});

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("pollRun", () => {
  it("stops polling as soon as the run reaches a terminal state", async () => {
    const states: RunState[] = ["queued", "running", "stale", "running"];
    const fetchRun = vi.fn(async () => run(states.shift()!));
    const seen: RunState[] = [];
    const res = await pollRun("r1", { signal: new AbortController().signal, onUpdate: (r) => seen.push(r.state), fetchRun, intervalMs: 1 });
    expect(res).toMatchObject({ kind: "done", run: { state: "stale" } });
    expect(seen).toEqual(["queued", "running", "stale"]);
    expect(fetchRun).toHaveBeenCalledTimes(3);
  });

  it("makes no request after the caller aborts (navigation, round switch, unmount)", async () => {
    vi.useFakeTimers();
    const ac = new AbortController();
    const fetchRun = vi.fn(async () => run("running"));
    const p = pollRun("r1", { signal: ac.signal, onUpdate: () => undefined, fetchRun, intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(2600);
    const before = fetchRun.mock.calls.length;
    ac.abort();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(await p).toEqual({ kind: "aborted" });
    expect(fetchRun.mock.calls.length).toBe(before);
  });

  it("is bounded: waits grow and polling gives up after the time budget", async () => {
    vi.useFakeTimers();
    const fetchRun = vi.fn(async () => run("running"));
    const p = pollRun("r1", { signal: new AbortController().signal, onUpdate: () => undefined, fetchRun,
      intervalMs: 1000, maxIntervalMs: 5000, maxMs: 30_000 });
    await vi.advanceTimersByTimeAsync(40_000);
    expect(await p).toEqual({ kind: "timeout" });
    expect(fetchRun.mock.calls.length).toBeLessThanOrEqual(12);  // never more than ~1 request a second
  });

  it("stops on session expiry and re-throws the 401 so the page can sign out", async () => {
    const fetchRun = vi.fn(async () => { throw new ApiError(401, "Session expired; sign in again"); });
    await expect(pollRun("r1", { signal: new AbortController().signal, onUpdate: () => undefined, fetchRun }))
      .rejects.toMatchObject({ status: 401 });
    expect(fetchRun).toHaveBeenCalledTimes(1);
  });

  it("tolerates a few network failures, then gives up", async () => {
    const fetchRun = vi.fn(async () => { throw new TypeError("network"); });
    await expect(pollRun("r1", { signal: new AbortController().signal, onUpdate: () => undefined, fetchRun, intervalMs: 1, maxErrors: 3 }))
      .rejects.toBeInstanceOf(TypeError);
    expect(fetchRun).toHaveBeenCalledTimes(3);
  });
});

describe("structured API errors", () => {
  it("expose the server's code, message and order/rider details", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response(JSON.stringify({
      detail: { code: "PRIORITY_CONFLICT", message: "Two first deliveries for one rider.", details: ["RW-1001", "RW-1002"] },
    }), { status: 422 })));
    const err = await api("/api/admin/rounds/x/optimize", { method: "POST" }).catch((e: unknown) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("Two first deliveries for one rider.");
    expect(err.code).toBe("PRIORITY_CONFLICT");
    expect(err.details).toEqual(["RW-1001", "RW-1002"]);
    expect(FIX[err.code!]).toBeTruthy();
  });

  it("read confirmation issues as details", () => {
    const e = new ApiError(422, "x", { code: "configuration_incomplete", message: "x", issues: [{ code: "a", reason: "has not chosen a destination" }] });
    expect(e.details).toEqual(["has not chosen a destination"]);
  });
});

describe("labels", () => {
  it("say recorded vs live and that durations exclude traffic", () => {
    expect(provenanceLabel({ real_road: true, recorded: true })).toMatch(/^Recorded real-road/);
    expect(provenanceLabel({ real_road: true, recorded: false })).toMatch(/^Live road distances/);
    expect(provenanceLabel({ real_road: false })).toBe("Not road distances");
    expect(trafficFree(600)).toBe("≈ 10 min (traffic-free estimate)");
    expect(km(22848)).toBe("22.8 km");
    expect(isTerminal("interrupted") && !isTerminal("queued")).toBe(true);
  });
});
