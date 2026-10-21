// Step 4D: the rider's own "Recalculate my route". Pure helpers for the screen: the one-shot device
// position read, the request bodies, and the wording of every refusal and run outcome.
//
// Privacy: a device position is read only when the rider taps the location action, once
// (`getCurrentPosition`, never `watchPosition`), with `maximumAge: 0` so an old fix is never reused. It
// exists only as a local value between the read and the request: it is never put into React state,
// storage, a URL, a log or an error message. The server applies its own limits again.

import { ApiError, KIND_LABEL, type DeliveryView, type OriginKind } from "./api";

export type RerouteOptions = NonNullable<DeliveryView["reroute"]>;
export type GpsLimits = RerouteOptions["gps_limits"];

export interface Fix { lat: number; lng: number; accuracy_m: number; age_s: number }

export type PositionProblem = "insecure" | "unsupported" | "denied" | "unavailable" | "timeout" | "inaccurate" | "stale" | "invalid";

export class PositionError extends Error {
  constructor(readonly problem: PositionProblem, message: string) { super(message); this.name = "PositionError"; }
}

export const GPS_TIMEOUT_MS = 15_000;

const FALLBACK_HINT = "You can still recalculate from another starting point below.";

/** What the rider is told for each reason a device position cannot be used (no coordinates ever). */
export const POSITION_TEXT: Record<PositionProblem, string> = {
  insecure: "Location isn't available on this connection. Your browser shares its location only on a secure connection "
    + "(HTTPS, or http://localhost), and this page is not on one. " + FALLBACK_HINT,
  unsupported: "This browser cannot share its location with this page. " + FALLBACK_HINT,
  denied: "Location access was denied, so nothing was requested from your phone. To use your location, allow it for this "
    + "site in your browser settings and try again. " + FALLBACK_HINT,
  unavailable: "Your phone could not work out its position (no usable GPS or network location right now). Try again outdoors. "
    + FALLBACK_HINT,
  timeout: "Your phone did not give a position in time. Try again outdoors. " + FALLBACK_HINT,
  inaccurate: "Your phone's position is not accurate enough to start a route from. " + FALLBACK_HINT,
  stale: "Your phone gave an old position, so it was not used. " + FALLBACK_HINT,
  invalid: "Your phone gave a position that could not be used. " + FALLBACK_HINT,
};

export function locationSupport(win: Pick<Window, "isSecureContext"> = window, nav: Pick<Navigator, "geolocation"> | object = navigator): "ok" | "insecure" | "unsupported" {
  if (win.isSecureContext === false) return "insecure";   // checked first: browsers expose the API but refuse it here
  return "geolocation" in nav && (nav as Navigator).geolocation ? "ok" : "unsupported";
}

export interface ReadOptions {
  signal: AbortSignal;
  win?: Pick<Window, "isSecureContext">;
  nav?: Pick<Navigator, "geolocation">;
  now?: () => number;
  timeoutMs?: number;
}

/** One fresh device position, requested now. Rejects with a PositionError (or an AbortError if cancelled) and
 * checks the limits the server published, so an unusable position is never sent. */
export function readCurrentPosition(limits: GpsLimits, opts: ReadOptions): Promise<Fix> {
  const nav = opts.nav ?? navigator;
  const support = locationSupport(opts.win ?? window, nav);
  if (support !== "ok") return Promise.reject(new PositionError(support, POSITION_TEXT[support]));
  const now = opts.now ?? Date.now;
  return new Promise<Fix>((resolve, reject) => {
    let settled = false;
    const finish = (run: () => void) => {
      if (settled) return;
      settled = true;
      opts.signal.removeEventListener("abort", onAbort);
      run();
    };
    const onAbort = () => finish(() => reject(new DOMException("Cancelled", "AbortError")));
    if (opts.signal.aborted) return onAbort();
    opts.signal.addEventListener("abort", onAbort);
    nav.geolocation.getCurrentPosition(
      (pos) => finish(() => {
        const { latitude: lat, longitude: lng, accuracy } = pos.coords;
        const age = Math.max(0, (now() - pos.timestamp) / 1000);
        if (![lat, lng, accuracy, age].every(Number.isFinite) || Math.abs(lat) > 90 || Math.abs(lng) > 180 || accuracy < 0) {
          return reject(new PositionError("invalid", POSITION_TEXT.invalid));
        }
        if (accuracy > limits.max_accuracy_m) {
          return reject(new PositionError("inaccurate", `Your phone's position is accurate only to about ${Math.round(accuracy)} m; `
            + `the limit is ${Math.round(limits.max_accuracy_m)} m. Try again outdoors. ${FALLBACK_HINT}`));
        }
        if (age > limits.max_age_s) {
          return reject(new PositionError("stale", `Your phone gave a position that is ${Math.round(age)} s old; the limit is `
            + `${Math.round(limits.max_age_s)} s, so it was not used. ${FALLBACK_HINT}`));
        }
        resolve({ lat, lng, accuracy_m: accuracy, age_s: age });
      }),
      (err) => finish(() => {
        const problem: PositionProblem = err.code === 1 ? "denied" : err.code === 3 ? "timeout" : "unavailable";
        reject(new PositionError(problem, POSITION_TEXT[problem]));
      }),
      { enableHighAccuracy: true, maximumAge: 0, timeout: opts.timeoutMs ?? GPS_TIMEOUT_MS },
    );
  });
}

// ---------------------------------------------------------------- requests

export interface RerouteBody {
  origin: { kind: OriginKind; lat?: number; lng?: number; accuracy_m?: number; age_s?: number; order_id?: string };
  expected_plan_version: number;
  expected_revision: number;
}
export interface Expected { plan: number; revision: number }

export function originBody(kind: OriginKind, expected: Expected, extra: { fix?: Fix; orderId?: string } = {}): RerouteBody {
  const origin: RerouteBody["origin"] = { kind };
  if (kind === "current_position" && extra.fix) Object.assign(origin, extra.fix);
  if (kind === "last_completed_stop" && extra.orderId) origin.order_id = extra.orderId;
  return { origin, expected_plan_version: expected.plan, expected_revision: expected.revision };
}

/** The plan version and revision the rider is looking at; the server refuses the request if either has moved. */
export function expectedOf(view: DeliveryView): Expected | null {
  if (!view.plan) return null;
  return { plan: view.plan.version, revision: view.plan.rider_route?.revision?.number ?? 0 };
}

export const ORIGIN_NAME: Record<OriginKind, string> = {
  current_position: "your current position (device location)",
  last_completed_stop: "your last completed stop (not your current position)",
  configured_start: "your configured start (not your current position)",
};

// ---------------------------------------------------------------- refusals (the POST was answered with a code)

export interface Refusal {
  text: string;
  /** Read the server state again so the screen shows what is true now (a refusal that depends on state). */
  reload: boolean;
  /** An existing own run to follow instead of starting another. */
  followRun?: string;
  /** The starting points may still be chosen (the refusal was about this one origin or a passing condition). */
  retry: boolean;
  tone: "warn" | "error";
}

const STATE_CODES = new Set(["ROUTE_CHANGED", "ORIGIN_CHANGED", "COMPLETED_STOP_AVAILABLE", "NO_COMPLETED_STOP", "ROUND_OUT_OF_DATE",
  "ROUND_REPLANNING", "NOT_CONFIRMED", "NO_PLAN", "NOT_IN_PLAN", "ACCOUNT_INACTIVE", "CONFIGURATION_NOT_READY", "ORDERS_NOT_READY"]);

/** A request the API answered with a refusal: nothing was started, so the previous route is untouched. */
export function describeRefusal(e: ApiError): Refusal {
  const code = e.code;
  if (code === "REROUTE_IN_PROGRESS") {
    return { text: "Your route is already being recalculated. Following that run.", reload: true, followRun: e.details[0], retry: false, tone: "warn" };
  }
  if (code === "PLANNING_BUSY") {
    return { text: "The planner is busy with other riders. Nothing was started and your route is unchanged. Try again in a moment.", reload: false, retry: true, tone: "warn" };
  }
  if (code === "POSITION_UNUSABLE") return { text: `${e.message} Your route is unchanged.`, reload: false, retry: true, tone: "warn" };
  if (code && STATE_CODES.has(code)) return { text: `${e.message} Your route is unchanged.`, reload: true, retry: false, tone: "warn" };
  return { text: `${e.message} Your route is unchanged.`, reload: false, retry: true, tone: e.status >= 500 ? "error" : "warn" };
}

// ---------------------------------------------------------------- run outcomes (the run was read)

export interface RunSummary {
  state: "queued" | "running" | "succeeded" | "failed" | "stale" | "interrupted";
  error: { code: string; message: string; details: string[] } | null;
  revision: number | null;
  origin_kind: OriginKind | null;
}

const KEPT = "Your previous route is still shown.";

const RUN_HINT: Record<string, string> = {
  ROUTING_ENGINE_UNAVAILABLE: "The road-routing engine is not available right now. Try again in a moment.",
  UNROUTABLE_ORIGIN: "No road was found near that starting point. Choose another starting point.",
  UNROUTABLE_ENDPOINT: "Your destination has no road connection. Ask your admin, or choose another destination.",
  UNROUTABLE_LOCATION: "A customer's pin has no road connection. Ask your admin to check it.",
  NO_FEASIBLE_PLAN: "No route fits your orders and capacity. Ask your admin.",
  INTERNAL: "Something went wrong on the server. Try again; if it keeps happening, tell your admin.",
  INPUTS_CHANGED: "Your orders or setup changed while it was being recalculated. Nothing was saved. Review your route, then recalculate again.",
  ROUND_REPLANNED: "Your admin replanned the round while it was being recalculated. Nothing was saved; the route shown is the new plan's.",
  INTERRUPTED: "The recalculation did not finish (the server restarted or it took too long). Nothing was saved.",
};

export type Outcome =
  | { kind: "failed" | "stale" | "interrupted"; title: string; text: string; reload: boolean }
  | { kind: "succeeded" };

/** The words for a finished run that did not save a route. `reload`: the saved route may now be different
 * (a new admin plan), so the screen reads it again. */
export function describeRun(run: RunSummary): Outcome {
  if (run.state === "succeeded") return { kind: "succeeded" };
  const code = run.error?.code ?? "";
  const hint = RUN_HINT[code] ?? run.error?.message ?? "Nothing was saved.";
  const title = run.state === "failed" ? "Could not recalculate your route"
    : run.state === "stale" ? "Not saved: something changed meanwhile" : "Recalculation interrupted";
  return { kind: run.state === "failed" || run.state === "stale" ? run.state : "interrupted", title, text: `${hint} ${KEPT}`, reload: run.state !== "failed" };
}

// ---------------------------------------------------------------- identity: plan version AND revision

/** What a request or run is anchored to. Revision numbers restart for every admin plan, so a revision number alone never
 * identifies a route: the plan version it hangs off is part of its identity.
 * - `planVersion`: the plan the request was made against (`null` when not established);
 * - `revision`: the rider's revision number on that plan when the request was made (0 = the plan's own route);
 * - `attribution`: "requested" (this screen sent the request: its base plan is the plan version it expected, which the server
 *   verified) or "discovered" (a run found by reading the server: its base plan and who started it are NOT established, so the
 *   wording never claims it as the rider's own tap). */
export interface Ctx { planVersion: number | null; revision: number; attribution: "requested" | "discovered" }

export function ctxFromView(view: DeliveryView | null, attribution: Ctx["attribution"]): Ctx {
  return { planVersion: view?.plan?.version ?? null, revision: view?.plan?.rider_route?.revision?.number ?? 0, attribution };
}

export type Verdict =
  | { kind: "saved"; revision: number; label: string; at: string }
  | { kind: "replaced"; was: number | null; now: number }            // an admin plan superseded the plan the request was made on
  | { kind: "newer"; revision: number; label: string; at: string }   // same plan, a later revision than the finished run's
  | { kind: "not_shown" };                                            // the effective view does not show the saved route (yet)

/** Is the run's saved route what the effective delivery view shows? Both the plan version and the revision must agree. */
export function judgeSaved(ctx: Ctx, runRevision: number | null, view: DeliveryView): Verdict {
  const plan = view.plan;
  if (!plan) return { kind: "not_shown" };
  if (ctx.planVersion !== null && plan.version !== ctx.planVersion) return { kind: "replaced", was: ctx.planVersion, now: plan.version };
  const rev = plan.rider_route?.revision ?? null;
  if (!rev || runRevision === null) return { kind: "not_shown" };
  const label = plan.rider_route?.origin_label ?? ORIGIN_NAME[rev.origin_kind];
  if (rev.number === runRevision) return { kind: "saved", revision: rev.number, label, at: rev.created_at };
  if (rev.number > runRevision) return { kind: "newer", revision: rev.number, label, at: rev.created_at };
  return { kind: "not_shown" };
}

/** After an unanswered request: what the server state shows, judged against the plan and revision the request was made on. */
export type StateVerdict =
  | { kind: "replaced"; was: number | null; now: number }
  | { kind: "changed"; revision: number; label: string; at: string }   // same plan, a different revision than before the request
  | { kind: "unchanged" }                                              // same plan, same revision, no run in progress
  | { kind: "unknown" };                                               // no plan to judge by

export function judgeState(ctx: Ctx, view: DeliveryView): StateVerdict {
  const plan = view.plan;
  if (!plan) return { kind: "unknown" };
  if (ctx.planVersion !== null && plan.version !== ctx.planVersion) return { kind: "replaced", was: ctx.planVersion, now: plan.version };
  const rev = plan.rider_route?.revision ?? null;
  const number = rev?.number ?? 0;
  if (rev && number !== ctx.revision) {
    return { kind: "changed", revision: number, label: plan.rider_route?.origin_label ?? ORIGIN_NAME[rev.origin_kind], at: rev.created_at };
  }
  return number === ctx.revision ? { kind: "unchanged" } : { kind: "unknown" };
}

/** An admin plan replaced the one the request was made on: say so, and never claim the requested route is shown or that
 * the saved route is unchanged. `how` says what is known about the request. */
export function replacedText(how: "finished" | "unanswered" | "discovered", was: number | null, now: number): { title: string; text: string } {
  const title = "Your admin replanned the round";
  const shown = `The route shown now is plan version ${now}'s route for you.`;
  if (how === "finished") {
    return { title, text: `Your recalculation was made on plan version ${was}, which your admin has since replaced (now version ${now}). ${shown} Your requested route is not shown. Recalculate again from here if you still want a new order.` };
  }
  if (how === "unanswered") {
    return { title, text: `Your admin replanned the round after you asked for a recalculation (plan version ${was} is now ${now}). Whether your request reached the server cannot be told, and a route made on the replaced plan is not used. ${shown}` };
  }
  return { title, text: `A recalculation of your route finished, but your admin has since replanned the round (now plan version ${now}). ${shown} The finished recalculation is not shown.` };
}

export const isActive = (s: RunSummary["state"]) => s === "queued" || s === "running";

/** Pending orders the rider holds in the round (in the saved sequence or outside it). */
export function pendingCount(view: DeliveryView): number {
  return view.sequence.reduce((n, s) => n + s.orders.length, 0) + view.unsequenced.length;
}

/** Which destination the rider's saved route still ends at after they changed their destination (server metadata:
 * `awaiting_recalculation`, which also covers new Home/Custom coordinates under the same kind). */
export function awaitingText(view: DeliveryView): string | null {
  const eff = view.plan?.rider_route;
  if (!eff?.awaiting_recalculation) return null;
  const saved = eff.destination.kind;
  const now = view.setup?.destination?.kind;
  return now && now !== saved
    ? `You changed your destination to ${KIND_LABEL[now]}. Your saved route still ends at ${KIND_LABEL[saved]} until you recalculate.`
    : `You changed the location of your ${KIND_LABEL[saved]} destination. Your saved route still ends at the previous ${KIND_LABEL[saved]} location until you recalculate.`;
}
