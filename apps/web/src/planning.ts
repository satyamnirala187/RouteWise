// Planning helpers for the 2C screens: bounded run polling, plain-language error guidance and
// formatting. Nothing here touches browser storage.
import { api, ApiError, TERMINAL_RUN_STATES, type PlanningRun, type Provenance, type RunState } from "./api";

export const isTerminal = (s: RunState) => TERMINAL_RUN_STATES.includes(s);

export interface PollOptions<R extends { state: RunState } = PlanningRun> {
  signal: AbortSignal;
  onUpdate: (run: R) => void;
  intervalMs?: number;     // first wait between polls
  maxIntervalMs?: number;  // waits grow to this
  maxMs?: number;          // give up (the run may still finish; the page offers a manual refresh)
  maxErrors?: number;      // consecutive network failures tolerated before giving up
  fetchRun?: (id: string, signal: AbortSignal) => Promise<R>;
}
export type PollResult<R extends { state: RunState } = PlanningRun> = { kind: "done"; run: R } | { kind: "aborted" } | { kind: "timeout" };

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(done, ms);
    function done() {
      clearTimeout(t);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done);
  });
}

const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";

/** Poll a run until it reaches a terminal state, the caller aborts (navigation, round switch,
 * unmount) or the time budget runs out (the same bounded lifecycle for admin runs and, since 4D, a rider's own). A 401 is re-thrown so the caller can end the session;
 * polling never continues after it. */
export async function pollRun<R extends { state: RunState } = PlanningRun>(runId: string, opts: PollOptions<R>): Promise<PollResult<R>> {
  const { signal, onUpdate } = opts;
  // The admin's planning-run endpoint unless the caller reads another kind of run (4D: a rider's own reroute).
  const fetchRun = opts.fetchRun ?? ((id, s) => api<PlanningRun>(`/api/admin/planning-runs/${id}`, { signal: s }) as unknown as Promise<R>);
  const maxMs = opts.maxMs ?? 5 * 60_000;
  const maxInterval = opts.maxIntervalMs ?? 5000;
  let interval = opts.intervalMs ?? 1000;
  let errors = 0;
  const started = Date.now();
  while (!signal.aborted) {
    try {
      const run = await fetchRun(runId, signal);
      if (signal.aborted) break;
      errors = 0;
      onUpdate(run);
      if (isTerminal(run.state)) return { kind: "done", run };
    } catch (e) {
      if (signal.aborted || isAbort(e)) break;
      if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404)) throw e;
      if (++errors >= (opts.maxErrors ?? 3)) throw e;
    }
    if (Date.now() - started >= maxMs) return { kind: "timeout" };
    await wait(interval, signal);
    interval = Math.min(maxInterval, Math.round(interval * 1.5));
  }
  return { kind: "aborted" };
}

/** What the admin can do about each coded refusal or run failure. The server's message and the
 * order codes / rider names it lists are always shown alongside. */
export const FIX: Record<string, string> = {
  NOT_READY: "Finish every item in the readiness checklist, then optimize.",
  RUN_IN_PROGRESS: "A plan is already being computed for this round; wait for it to finish.",
  PLANNING_BUSY: "The planner is busy with other rounds. Try again in a moment.",
  NOTHING_TO_PLAN: "There are no Pending orders in this round.",
  ROUND_TOO_LARGE: "Split the round into smaller imports or use fewer riders, within the limits shown above.",
  INSUFFICIENT_CAPACITY: "Raise riders' capacity on Round setup, or add another participating rider.",
  HELD_ORDERS_EXCEED_CAPACITY: "Postponed and Completed orders count toward their rider's capacity; raise that capacity.",
  INVALID_LOCK: "Lock orders only to riders who participate in this round.",
  LOCK_EXCEEDS_CAPACITY: "More orders are locked to a rider than their capacity; remove some locks or raise capacity.",
  MANUAL_ASSIGNMENT_MISSING: "Manual mode needs an owner lock on every Pending order; use bulk owner assignment on Orders.",
  PRIORITY_CONFLICT: "Each rider can have only one first delivery; remove a first-delivery flag or a lock.",
  PRIORITY_NOT_PENDING: "Only Pending orders can be a first delivery.",
  OWNERSHIP_CHANGE_UNSUPPORTED: "Postponed and Completed orders keep their rider; handing them over is not supported yet.",
  POSTPONED_WITHOUT_OWNER: "Set these Postponed orders back to Pending to plan them.",
  OWNER_NOT_PARTICIPATING: "These Postponed orders belong to a rider who left the round; add the rider back or set the orders to Pending.",
  INPUTS_CHANGED: "Check what changed (for example a rider's destination, a pin or a capacity), then optimize again.",
  INTERRUPTED: "The server restarted or the run took too long. Optimize again.",
  UNROUTABLE_LOCATION: "These orders have no road connection for the vehicle; fix their pins on Orders.",
  UNROUTABLE_ENDPOINT: "A rider's start or destination has no road connection; change the depot or ask the rider to choose another destination.",
  NO_FEASIBLE_PLAN: "No plan meets the capacity, locks and first-delivery rules together; relax one of them.",
  NOT_ROAD_DISTANCES: "No plan is made without real road distances. Check the local routing data.",
  ROUTING_ENGINE_UNAVAILABLE: "Check that the local Valhalla tiles are built (see DEVELOPMENT.md), then optimize again.",
  INTERNAL: "Try again; if it happens again, check the API log for this run.",
};

export const RUN_STATE_LABEL: Record<RunState, string> = {
  queued: "Waiting to start", running: "Computing road routes", succeeded: "Plan saved",
  failed: "Failed — nothing saved", stale: "Rejected — the round changed during the run", interrupted: "Interrupted — nothing saved",
};

export const km = (m: number) => `${(m / 1000).toFixed(1)} km`;
export const trafficFree = (s: number) => `≈ ${Math.max(1, Math.round(s / 60))} min (traffic-free estimate)`;

/** "Recorded" vs "live" is shown on every plan; a recorded matrix is replayed test data. */
export function provenanceLabel(p: Provenance): string {
  if (!p.real_road) return "Not road distances";
  return p.recorded
    ? "Recorded real-road distances (replayed test data from local Valhalla)"
    : "Live road distances from local Valhalla (OpenStreetMap data)";
}
