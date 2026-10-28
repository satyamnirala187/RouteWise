import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DeliveryView } from "./api";
import { POLL, useReroute } from "./useReroute";

// The reroute flow against a fake server (fetch is stubbed) and a fake device (mocked geolocation).

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;
let handler: Handler;
let calls: { url: string; method: string; body: string | undefined }[];

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
const refusal = (status: number, code: string, details: string[] = []) => json(status, { detail: { code, message: `server: ${code}`, details } });
const run = (state: string, extra: Record<string, unknown> = {}) => json(200, { id: "run-1", state, origin_kind: "configured_start", error: null, revision: null, ...extra });
const posts = () => calls.filter((c) => c.method === "POST");

/** The rider's delivery view: `revision` on plan `planVersion` (revision numbers restart with every admin plan). */
const view = (over: Partial<NonNullable<DeliveryView["reroute"]>> = {}, revision: number | null = null, planVersion = 1): DeliveryView => ({
  round_id: "r1", round_name: "Round", participating: true, setup: null,
  plan: {
    version: planVersion, is_current: true, created_at: "2026-10-20T08:00:00Z", out_of_date: false, progress_since_plan: false, superseded_versions: 0,
    real_road: true, recorded: true, route: null,
    rider_route: {
      revision: revision === null ? null : { number: revision, trigger: "rider_request", origin_kind: "configured_start", origin_order_code: null, created_at: "2026-10-20T08:30:00Z" },
      origin_label: "your configured start, not your current position", vehicle: "scooter", destination: { kind: "home", label: null },
      open_route: false, road_distance_m: 1000, road_duration_s: 300, awaiting_recalculation: null,
    },
  },
  sequence: [], unsequenced: [], postponed: [], completed: [],
  reroute: { available: true, blocked: null, in_progress_run_id: null, last_completed_stop: null, configured_start_allowed: true,
             gps_limits: { max_accuracy_m: 100, max_age_s: 60 }, ...over },
});

function setup(initial: { roundId?: string; view?: DeliveryView; reload?: (id: string) => Promise<DeliveryView | null> } = {}) {
  const onUnauthorized = vi.fn();
  const reload = vi.fn(initial.reload ?? (async () => view({}, 1)));
  const hook = renderHook((p: { roundId: string | null; view: DeliveryView | null }) =>
    useReroute({ roundId: p.roundId, view: p.view, reload, onUnauthorized, online: true, statusBusy: false }),
  { initialProps: { roundId: initial.roundId ?? "r1", view: initial.view ?? view() } });
  return { ...hook, reload, onUnauthorized };
}

beforeEach(() => {
  calls = [];
  Object.assign(POLL, { intervalMs: 5, maxIntervalMs: 10, budgetMs: 2000, maxErrors: 3 });
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body as string | undefined });
    return handler(url, init);
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("starting a recalculation", () => {
  it("sends one request for a double tap, and shows success only after the effective view shows the revision", async () => {
    handler = (_url, init) => init.method === "POST" ? json(202, { id: "run-1", state: "queued" }) : run("succeeded", { revision: 1 });
    const { result, reload } = setup();
    act(() => { void result.current.start("configured_start"); void result.current.start("configured_start"); });
    await waitFor(() => expect(result.current.result?.tone).toBe("ok"));
    expect(posts()).toHaveLength(1);
    expect(JSON.parse(posts()[0].body!)).toEqual({ origin: { kind: "configured_start" }, expected_plan_version: 1, expected_revision: 0 });
    expect(reload).toHaveBeenCalled();                     // the view was read after the run ended
    expect(result.current.result?.text).toMatch(/^Route recalculated from your configured start, not your current position at /);
    expect(result.current.phase).toBe("idle");
  });

  it("does not claim success when the server's route has not reached the screen", async () => {
    handler = (_u, init) => init.method === "POST" ? json(202, { id: "run-1", state: "queued" }) : run("succeeded", { revision: 2 });
    const { result } = setup({ reload: async () => view({}, 1) });   // the view still shows revision 1
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.result).toMatchObject({ tone: "warn" });
    expect(result.current.unresolved).toEqual({ kind: "confirm" });
    expect(result.current.result?.text).toContain("does not show that route yet");
  });

  it("reports failed, stale and interrupted runs separately and keeps the previous route", async () => {
    for (const [state, code, tone, title] of [
      ["failed", "ROUTING_ENGINE_UNAVAILABLE", "error", "Could not recalculate your route"],
      ["stale", "INPUTS_CHANGED", "warn", "Not saved: something changed meanwhile"],
      ["interrupted", "INTERRUPTED", "warn", "Recalculation interrupted"],
    ] as const) {
      handler = (_u, init) => init.method === "POST" ? json(202, { id: "run-1", state: "queued" })
        : run(state, { error: { code, message: "server text", details: [] } });
      const { result } = setup();
      await act(async () => { await result.current.start("configured_start"); });
      expect(result.current.result).toMatchObject({ tone, title });
      expect(result.current.result?.text).toContain("Your previous route is still shown.");
    }
  });
});

describe("an unanswered request is an unknown outcome", () => {
  it("reads the server state before offering anything, and never sends the request again by itself", async () => {
    handler = () => { throw new TypeError("network"); };
    const { result, reload } = setup({ reload: async () => view({}, null) });
    await act(async () => { await result.current.start("configured_start"); });
    expect(reload).toHaveBeenCalled();
    expect(result.current.result).toMatchObject({ title: "Nothing was recalculated" });
    expect(posts()).toHaveLength(1);
  });

  it("follows a run the lost request did start", async () => {
    let first = true;
    handler = (_u, init) => {
      if (init.method === "POST") throw new TypeError("network");
      if (first) { first = false; return run("running"); }
      return run("succeeded", { revision: 1 });
    };
    let reads = 0;
    const { result } = setup({ reload: async () => (reads++ === 0 ? view({ in_progress_run_id: "run-1", available: false }) : view({}, 1)) });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.result?.tone).toBe("ok");
    expect(posts()).toHaveLength(1);
  });

  it("offers only a read-only check while the state cannot be read", async () => {
    handler = () => { throw new TypeError("network"); };
    const { result, reload } = setup({ reload: async () => { throw new TypeError("still offline"); } });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.result).toMatchObject({ title: "Could not confirm" });
    expect(result.current.unresolved).toEqual({ kind: "unknown" });
    await act(async () => { await result.current.checkAgain(); });             // still unreadable: the same read-only offer
    expect(result.current.result).toMatchObject({ title: "Could not confirm" });
    expect(result.current.unresolved).toEqual({ kind: "unknown" });
    reload.mockImplementation(async () => view({}, null));
    await act(async () => { await result.current.checkAgain(); });             // readable now: the server state decides
    expect(result.current.result).toMatchObject({ title: "Nothing was recalculated" });
    expect(result.current.unresolved).toBeNull();                               // the server state is established again
    expect(posts()).toHaveLength(1);   // none of the checks sent a recalculation
  });
});

describe("refusals", () => {
  it("follows the run named by REROUTE_IN_PROGRESS instead of starting another", async () => {
    handler = (_u, init) => init.method === "POST" ? refusal(409, "REROUTE_IN_PROGRESS", ["run-1"]) : run("succeeded", { revision: 1 });
    const { result } = setup();
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.result?.tone).toBe("ok");
    expect(posts()).toHaveLength(1);
  });

  it("treats a coded 503 as a definite refusal (nothing started) and reloads for a state refusal", async () => {
    handler = () => refusal(503, "PLANNING_BUSY");
    const busy = setup();
    await act(async () => { await busy.result.current.start("configured_start"); });
    expect(busy.result.current.result?.text).toContain("planner is busy");
    expect(busy.result.current.phase).toBe("choosing");
    expect(busy.reload).not.toHaveBeenCalled();

    handler = () => refusal(409, "ROUTE_CHANGED");
    const changed = setup();
    await act(async () => { await changed.result.current.start("configured_start"); });
    expect(changed.reload).toHaveBeenCalled();
    expect(changed.result.current.result?.text).toContain("Your route is unchanged");
  });

  it("ends the session on a 401", async () => {
    handler = () => json(401, { detail: "Session expired" });
    const { result, onUnauthorized } = setup();
    await act(async () => { await result.current.start("configured_start"); });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

describe("the device position", () => {
  const stubGeolocation = (impl: (ok: PositionCallback, err: PositionErrorCallback) => void) => {
    const getCurrentPosition = vi.fn(impl);
    vi.stubGlobal("navigator", { ...navigator, geolocation: { getCurrentPosition, watchPosition: vi.fn() } });
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    return getCurrentPosition;
  };

  it("is read once on the tap, sent once, and appears in no state or message", async () => {
    const get = stubGeolocation((ok) => ok({ coords: { latitude: 28.688345, longitude: 77.214788, accuracy: 15 }, timestamp: Date.now() } as GeolocationPosition));
    handler = (_u, init) => init.method === "POST" ? json(202, { id: "run-1", state: "queued" }) : run("succeeded", { revision: 1 });
    const { result } = setup();
    await act(async () => { await result.current.start("current_position"); });
    expect(get).toHaveBeenCalledTimes(1);
    expect(JSON.parse(posts()[0].body!).origin).toMatchObject({ kind: "current_position", lat: 28.688345, lng: 77.214788, accuracy_m: 15 });
    expect(JSON.stringify([result.current.result, result.current.problem, result.current.phase])).not.toMatch(/28\.68|77\.21/);
  });

  it("returns to the choices with a reason when the phone refuses, and sends nothing", async () => {
    stubGeolocation((_ok, err) => err({ code: 1, message: "denied" } as GeolocationPositionError));
    handler = () => json(202, { id: "run-1", state: "queued" });
    const { result } = setup();
    await act(async () => { await result.current.start("current_position"); });
    expect(result.current.phase).toBe("choosing");
    expect(result.current.problem).toContain("did not allow location");
    expect(posts()).toHaveLength(0);
  });

  it("can be cancelled while waiting, and then sends nothing", async () => {
    stubGeolocation(() => undefined);   // the phone never answers
    handler = () => json(202, { id: "run-1", state: "queued" });
    const { result } = setup();
    act(() => { void result.current.start("current_position"); });
    await waitFor(() => expect(result.current.phase).toBe("locating"));
    act(() => result.current.cancelLocating());
    await waitFor(() => expect(result.current.phase).toBe("choosing"));
    expect(result.current.problem).toBeNull();
    expect(posts()).toHaveLength(0);
  });
});

describe("discovering and dropping runs", () => {
  it("follows a run of the rider's own that already exists (a page refresh) instead of starting one", async () => {
    handler = () => run("succeeded", { revision: 1 });
    const { result } = setup({ view: view({ in_progress_run_id: "run-1", available: false }) });
    await waitFor(() => expect(result.current.result?.tone).toBe("ok"));
    expect(posts()).toHaveLength(0);
  });

  it("drops a late answer once another round is selected", async () => {
    let finish!: () => void;
    const slow = new Promise<void>((r) => { finish = r; });
    handler = async (_u, init) => {
      if (init.method === "POST") return json(202, { id: "run-1", state: "queued" });
      await slow;
      return run("succeeded", { revision: 1 });
    };
    const { result, rerender, reload } = setup();
    act(() => { void result.current.start("configured_start"); });
    await waitFor(() => expect(result.current.phase).toBe("running"));
    rerender({ roundId: "r2", view: { ...view(), round_id: "r2" } });
    expect(result.current.phase).toBe("idle");
    finish();
    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.result).toBeNull();      // round 2 never shows round 1's outcome
    expect(result.current.phase).toBe("idle");
    expect(reload).not.toHaveBeenCalled();         // and the old run's result was never loaded over it
  });

  it("stops reading on unmount (navigation or sign-out)", async () => {
    handler = async (_u, init) => init.method === "POST" ? json(202, { id: "run-1", state: "queued" }) : run("running");
    const { result, unmount } = setup();
    act(() => { void result.current.start("configured_start"); });
    await waitFor(() => expect(result.current.phase).toBe("running"));
    unmount();
    const seen = calls.length;
    await new Promise((r) => setTimeout(r, 60));
    expect(calls.length).toBeLessThanOrEqual(seen + 1);   // at most the read already in flight
  });
});

// ---------------------------------------------------------------------------------------------------------------
// Correction pass: a route is identified by its PLAN VERSION and its revision number together.

describe("identity: plan version and revision are judged together", () => {
  const sendAndFinish = (revision: number) => (_u: string, init: RequestInit) =>
    init.method === "POST" ? json(202, { id: "run-1", state: "queued" }) : run("succeeded", { revision });

  it("does not show a finished run as the requested route when an admin replan reused its revision number", async () => {
    handler = sendAndFinish(1);
    // the run saved revision 1 on plan 1; before the view loads, an admin plan 2 exists and the rider has a revision 1 on it too
    const { result, reload } = setup({ reload: async () => view({}, 1, 2) });
    await act(async () => { await result.current.start("configured_start"); });
    expect(reload).toHaveBeenCalled();
    expect(result.current.result).toMatchObject({ tone: "warn", title: "Your admin replanned the round" });
    expect(result.current.result?.text).toContain("plan version 1");
    expect(result.current.result?.text).toContain("version 2");
    expect(result.current.result?.text).toContain("Your requested route is not shown");
    expect(result.current.result?.text).not.toMatch(/Route recalculated|Your new order/);
    expect(result.current.unresolved).toBeNull();                                // the state is established: the new plan's route
    expect(result.current.phase).toBe("idle");
  });

  it("says the same when the new plan has no revision of the rider's yet", async () => {
    handler = sendAndFinish(1);
    const { result } = setup({ reload: async () => view({}, null, 2) });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.result?.title).toBe("Your admin replanned the round");
  });

  it("after a lost answer and a different admin plan, never says the route is unchanged (reused revision numbers included)", async () => {
    handler = () => { throw new TypeError("network"); };
    for (const revisionNow of [null, 1]) {            // plan 2 shows no revision, or the very number the rider was looking at
      const { result } = setup({ view: view({}, 1, 1), reload: async () => view({}, revisionNow, 2) });
      await act(async () => { await result.current.start("configured_start"); });
      expect(result.current.result?.title).toBe("Your admin replanned the round");
      expect(result.current.result?.text).toContain("Whether your request reached the server cannot be told");
      expect(result.current.result?.text).not.toMatch(/unchanged|Nothing was recalculated/);
      expect(result.current.unresolved).toBeNull();
    }
  });

  it("keeps the original request's context across read-only checks, not the screen as it is now", async () => {
    handler = sendAndFinish(1);
    let reads = 0;
    // the screen (the view prop) still shows plan 1; the server reads: first fails, then plan 2 with a reused revision number
    const { result } = setup({ reload: async () => { if (reads++ === 0) throw new TypeError("offline"); return view({}, 1, 2); } });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.unresolved).toEqual({ kind: "confirm" });
    await act(async () => { await result.current.checkAgain(); });
    expect(result.current.result?.title).toBe("Your admin replanned the round");
    expect(result.current.unresolved).toBeNull();
  });

  it("keeps the request's own starting revision even after the screen's view moved on (for example after a status change)", async () => {
    handler = () => { throw new TypeError("network"); };
    let readable = false;
    const { result, rerender } = setup({ view: view({}, null, 1), reload: async () => { if (!readable) throw new TypeError("offline"); return view({}, 1, 1); } });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.unresolved).toEqual({ kind: "unknown" });
    rerender({ roundId: "r1", view: view({}, 1, 1) });                         // a confirmed status change delivered a view that already shows revision 1
    readable = true;
    await act(async () => { await result.current.checkAgain(); });
    expect(result.current.result?.title).toBe("Your route was recalculated");  // judged against revision 0 (what the request was made on), not 1
    expect(result.current.result?.title).not.toBe("Nothing was recalculated");
  });

  it("does the same for an unanswered request that is checked again after the plan changed", async () => {
    handler = () => { throw new TypeError("network"); };
    let reads = 0;
    const { result } = setup({ view: view({}, 1, 1), reload: async () => { if (reads++ === 0) throw new TypeError("offline"); return view({}, 1, 2); } });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.unresolved).toEqual({ kind: "unknown" });
    await act(async () => { await result.current.checkAgain(); });
    expect(result.current.result?.title).toBe("Your admin replanned the round");
    expect(posts()).toHaveLength(1);
  });

  it("shows a newer revision of the same plan as newer, not as the finished run's", async () => {
    handler = sendAndFinish(1);
    const { result } = setup({ reload: async () => view({}, 2, 1) });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.result).toMatchObject({ tone: "warn", title: "A newer route is shown" });
    expect(result.current.result?.text).not.toMatch(/^Route recalculated/);
  });

  it("describes a changed route after a lost answer as made after the request, not as exactly the request's", async () => {
    handler = () => { throw new TypeError("network"); };
    const { result } = setup({ view: view({}, null, 1), reload: async () => view({}, 1, 1) });
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.result).toMatchObject({ tone: "ok", title: "Your route was recalculated" });
    expect(result.current.result?.text).toContain("cannot be matched to it exactly");
  });

  it("uses conservative wording for a run found by reading the server (its starter and plan are not established)", async () => {
    handler = () => run("succeeded", { revision: 1 });
    const { result } = setup({ view: view({ in_progress_run_id: "run-1", available: false }), reload: async () => view({}, 1, 1) });
    await waitFor(() => expect(result.current.result?.tone).toBe("ok"));
    expect(result.current.result?.title).toBe("Your route was recalculated");
    expect(result.current.result?.text).toMatch(/^A recalculation of your route finished\./);
    expect(result.current.result?.text).not.toMatch(/^Route recalculated from/);
    expect(posts()).toHaveLength(0);
  });

  it("says a found run's result is not shown when an admin plan replaced the one the rider was looking at", async () => {
    handler = () => run("succeeded", { revision: 1 });
    const { result } = setup({ view: view({ in_progress_run_id: "run-1", available: false }, null, 1), reload: async () => view({}, 1, 2) });
    await waitFor(() => expect(result.current.result?.tone).toBe("warn"));
    expect(result.current.result?.title).toBe("Your admin replanned the round");
    expect(result.current.result?.text).toContain("The finished recalculation is not shown.");
  });
});

describe("what is unresolved is kept apart from the message about it", () => {
  const lostAndUnreadable = () => {
    handler = () => { throw new TypeError("network"); };
    return setup({ reload: async () => { throw new TypeError("still offline"); } });
  };

  it("keeps new requests impossible after the message is dismissed, in the hook as well as on the buttons", async () => {
    const { result } = lostAndUnreadable();
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.unresolved).toEqual({ kind: "unknown" });
    act(() => result.current.dismiss());
    expect(result.current.result).toBeNull();                                   // the message is gone ...
    expect(result.current.unresolved).toEqual({ kind: "unknown" });             // ... the uncertainty is not
    await act(async () => { await result.current.start("configured_start"); await result.current.start("current_position"); });
    act(() => result.current.open());
    expect(posts()).toHaveLength(1);                                            // no second request, of any kind
    expect(result.current.phase).toBe("idle");                                  // and the choices cannot be opened
    await act(async () => { await result.current.checkAgain(); });              // the read-only check is still available
    expect(result.current.unresolved).toEqual({ kind: "unknown" });             // reads still fail: still unresolved
    expect(result.current.result?.title).toBe("Could not confirm");
    act(() => result.current.dismiss());
    await act(async () => { await result.current.start("configured_start"); });
    expect(posts()).toHaveLength(1);
  });

  it("is not cleared by a confirmed status change (retire), while an ordinary old message is", async () => {
    const { result } = lostAndUnreadable();
    await act(async () => { await result.current.start("configured_start"); });
    act(() => result.current.retire());
    expect(result.current.result?.title).toBe("Could not confirm");             // still shown: it is still unresolved
    expect(result.current.unresolved).toEqual({ kind: "unknown" });

    handler = sendAndFinishOk;
    const ok = setup();
    await act(async () => { await ok.result.current.start("configured_start"); });
    expect(ok.result.current.result?.tone).toBe("ok");
    act(() => ok.result.current.retire());
    expect(ok.result.current.result).toBeNull();                                // resolved: an old success message is retired
  });

  it("is established again only by a successful read, which restores the actions", async () => {
    handler = () => { throw new TypeError("network"); };
    let readable = false;
    let saved: number | null = null;                                            // the revision the server shows once a recalculation was saved
    const { result } = setup({ view: view({}, null, 1), reload: async () => { if (!readable) throw new TypeError("offline"); return view({}, saved, 1); } });
    await act(async () => { await result.current.start("configured_start"); });
    act(() => result.current.dismiss());
    expect(result.current.canStart).toBe(true);                                 // the hook's own flag allows it, which is why start() itself must refuse
    await act(async () => { await result.current.start("configured_start"); });
    expect(posts()).toHaveLength(1);

    readable = true;                                                            // the server can be read now
    await act(async () => { await result.current.checkAgain(); });
    expect(result.current.unresolved).toBeNull();
    expect(result.current.result?.title).toBe("Nothing was recalculated");
    handler = sendAndFinishOk;                                                  // and a new request is possible again
    saved = 1;
    await act(async () => { await result.current.start("configured_start"); });
    expect(posts()).toHaveLength(2);
    expect(result.current.result?.tone).toBe("ok");
    expect(result.current.unresolved).toBeNull();
  });

  it("keeps a run that could not be followed unresolved until it is read", async () => {
    handler = (_u, init) => { if (init.method === "POST") return json(202, { id: "run-1", state: "queued" }); throw new TypeError("offline"); };
    const { result } = setup();
    await act(async () => { await result.current.start("configured_start"); });
    expect(result.current.unresolved).toEqual({ kind: "run" });
    act(() => result.current.dismiss());
    await act(async () => { await result.current.start("configured_start"); });
    expect(posts()).toHaveLength(1);
    handler = () => run("succeeded", { revision: 1 });
    await act(async () => { await result.current.checkAgain(); });
    expect(result.current.unresolved).toBeNull();
    expect(result.current.result?.tone).toBe("ok");
  });
});

const sendAndFinishOk = (_u: string, init: RequestInit) =>
  init.method === "POST" ? json(202, { id: "run-1", state: "queued" }) : run("succeeded", { revision: 1 });
