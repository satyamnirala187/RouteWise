import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, isDefiniteRefusal, type DeliveryView, type OriginKind } from "./api";
import { pollRun } from "./planning";
import {
  ctxFromView, describeRefusal, describeRun, expectedOf, judgeSaved, judgeState, originBody, PositionError, readCurrentPosition,
  replacedText, type Ctx, type Fix, type RunSummary,
} from "./reroute";

// Step 4D: the rider's own "Recalculate my route" as one small state machine.
//
//   idle → choosing → [locating] → submitting → running → finishing → idle (+ a result)
//
// Rules this hook keeps:
// - one request at a time: a ref lock is taken synchronously on the first tap, so a double tap sends nothing twice;
// - a request is made only when the rider taps an origin; nothing is preselected, remembered or retried by itself;
// - an unanswered POST is an UNKNOWN outcome: the server state is read before anything else is offered;
// - success is shown only after the run is confirmed by the server AND the effective delivery view shows it: the plan
//   version and the revision number are judged TOGETHER (revision numbers restart with every admin plan);
// - what is not known is kept apart from the message about it: while the server state is unresolved, no new request can be
//   started (in this hook as well as on the buttons), whatever happens to the message; only read-only checks remain;
// - everything started here is dropped on a round change, navigation or sign-out (epoch + abort);
// - a device position is a local value between the read and the request only (never state, storage or log).

export type Phase = "idle" | "choosing" | "locating" | "submitting" | "running" | "checking" | "finishing";
export type Result = { tone: "ok" | "warn" | "error"; title: string; text: string };

interface RerouteRun extends RunSummary { id: string }

/** What is still unknown about a request or run, with the context it was made in. It is kept across read-only checks and is
 * NOT the message: dismissing the message leaves it in place until a read of the server establishes the current state.
 * - "unknown": a request got no usable answer; did it start anything?
 * - "confirm": a run ended with a saved route, but the effective view could not be read (or does not show it) yet;
 * - "run": a run is still going (or could not be followed to its end). */
type Pending =
  | { kind: "unknown"; ctx: Ctx }
  | { kind: "confirm"; ctx: Ctx; run: RerouteRun }
  | { kind: "run"; ctx: Ctx; runId: string };
export type Unresolved = { kind: Pending["kind"] };

export const POLL = { intervalMs: 700, maxIntervalMs: 2000, budgetMs: 90_000, maxErrors: 3 };

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const BUSY: Phase[] = ["locating", "submitting", "running", "checking", "finishing"];

export function useReroute({ roundId, view, reload, onUnauthorized, online, statusBusy }: {
  roundId: string | null;
  view: DeliveryView | null;
  /** Read the delivery view again and apply it to the screen. Resolves with it, or null if a newer load or another
   * round replaced this request; rejects if it could not be read. */
  reload: (roundId: string) => Promise<DeliveryView | null>;
  onUnauthorized: () => void;
  online: boolean;
  statusBusy: boolean;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<Result | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [unresolved, setUnresolved] = useState<Unresolved | null>(null);
  const pending = useRef<Pending | null>(null);   // the synchronous twin of `unresolved`, with its full context
  const lock = useRef(false);                 // one reroute action at a time (set synchronously)
  const epoch = useRef(0);                    // bumped on a round change or unmount: late answers are dropped
  const ac = useRef<AbortController | null>(null);
  const viewRef = useRef<DeliveryView | null>(view);
  viewRef.current = view;
  const followed = useRef(new Set<string>()); // runs already followed automatically (a manual check may repeat one)
  const checkStateRef = useRef<((my: number, ctx: Ctx) => Promise<void>) | null>(null);   // follow() and checkState() call each other
  const callbacks = useRef({ reload, onUnauthorized });
  callbacks.current = { reload, onUnauthorized };

  /** End an action. `unknown` (the state is still not established) keeps the context for read-only checks; otherwise the
   * server state is established and everything may be offered again. */
  const settle = useCallback((next: Result | null, nextPhase: Phase = "idle", unknown: Pending | null = null) => {
    lock.current = false;
    ac.current = null;
    pending.current = unknown;
    setUnresolved(unknown ? { kind: unknown.kind } : null);
    setResult(next);
    setPhase(nextPhase);
  }, []);

  /** Read the delivery view, tolerating being replaced once by a newer load. */
  const readView = useCallback(async (id: string, my: number): Promise<DeliveryView | null> => {
    for (let i = 0; i < 2; i++) {
      const v = await callbacks.current.reload(id);
      if (epoch.current !== my) return null;
      if (v) return v;
    }
    return null;
  }, []);

  const unauthorized = (e: unknown, my: number) => {
    if (e instanceof ApiError && e.status === 401) { if (epoch.current === my) callbacks.current.onUnauthorized(); return true; }
    return false;
  };

  /** The run finished with a saved route: show success only once the effective view shows THAT route, judged by plan
   * version and revision number together. */
  const confirmSaved = useCallback(async (id: string, my: number, run: RerouteRun, ctx: Ctx) => {
    setPhase("finishing");
    const again: Pending = { kind: "confirm", ctx, run };
    let v: DeliveryView | null;
    try { v = await readView(id, my); } catch (e) {
      if (epoch.current !== my || unauthorized(e, my)) return;
      return settle({ tone: "warn", title: "Recalculated, but not loaded yet",
        text: "The server reports a finished recalculation, but your route could not be loaded here. Check again to see it." }, "idle", again);
    }
    if (epoch.current !== my) return;
    if (!v) return settle({ tone: "warn", title: "Recalculated, but not loaded yet",
      text: "The server reports a finished recalculation, but your route could not be read just now. Check again to see it." }, "idle", again);
    const verdict = judgeSaved(ctx, run.revision, v);
    if (verdict.kind === "replaced") {
      const how = ctx.attribution === "requested" ? "finished" : "discovered";
      return settle({ tone: "warn", ...replacedText(how, verdict.was, verdict.now) });
    }
    if (verdict.kind === "not_shown") {
      return settle({ tone: "warn", title: "Recalculated, but not loaded yet",
        text: "The server reports a finished recalculation, but your screen does not show that route yet. Check again to see it." }, "idle", again);
    }
    if (verdict.kind === "newer") {
      return settle({ tone: "warn", title: "A newer route is shown",
        text: `The recalculation that finished is not the latest: your saved route is now revision ${verdict.revision}, recalculated from ${verdict.label} at ${clock(verdict.at)}. It is shown below.` });
    }
    if (ctx.attribution === "requested") {
      return settle({ tone: "ok", title: "Route recalculated",
        text: `Route recalculated from ${verdict.label} at ${clock(verdict.at)}. Your new order is shown below.` });
    }
    // A run found by reading the server: who started it is not established, so it is not claimed as this screen's request.
    settle({ tone: "ok", title: "Your route was recalculated",
      text: `A recalculation of your route finished. Your saved route is now revision ${verdict.revision}, recalculated from ${verdict.label} at ${clock(verdict.at)}.` });
  }, [readView, settle]);

  /** Follow one of the rider's own runs until it ends (bounded; stops on navigation, round change or sign-out). */
  const follow = useCallback(async (runId: string, my: number, ctx: Ctx) => {
    followed.current.add(runId);
    setPhase("running");
    const controller = new AbortController();
    ac.current = controller;
    const id = roundId!;
    try {
      const r = await pollRun<RerouteRun>(runId, {
        signal: controller.signal, onUpdate: () => undefined, intervalMs: POLL.intervalMs, maxIntervalMs: POLL.maxIntervalMs,
        maxMs: POLL.budgetMs, maxErrors: POLL.maxErrors,
        fetchRun: (rid, signal) => api<RerouteRun>(`/api/rider/reroutes/${rid}`, { signal }),
      });
      if (epoch.current !== my || r.kind === "aborted") return;
      if (r.kind === "timeout") {
        return settle({ tone: "warn", title: "Still recalculating",
          text: "This is taking longer than expected. It may still finish; nothing else will be sent, and nothing new can be started until it is known. Your previous route is still shown." },
          "idle", { kind: "run", ctx, runId });
      }
      const outcome = describeRun(r.run);
      if (outcome.kind === "succeeded") return void (await confirmSaved(id, my, r.run, ctx));
      let reloaded = false;
      if (outcome.reload) { try { await readView(id, my); reloaded = true; } catch { /* the message below still stands */ } }
      if (epoch.current !== my) return;
      settle({ tone: outcome.kind === "failed" ? "error" : "warn", title: outcome.title,
        text: outcome.text + (outcome.reload && !reloaded ? " Refresh to check your current route." : "") });
    } catch (e) {
      if (epoch.current !== my || unauthorized(e, my)) return;
      if (e instanceof ApiError && e.status === 404) return void (await checkStateRef.current?.(my, ctx));   // that run is gone: read the state itself
      settle({ tone: "warn", title: "Lost contact while checking",
        text: "Could not reach the server to see how the recalculation ended. It may still finish. Nothing else will be sent, and nothing new can be started until it is known; check again when you are connected. Your previous route is still shown." },
        "idle", { kind: "run", ctx, runId });
    }
  }, [roundId, confirmSaved, readView, settle]);

  /** After an unanswered request: read the server state, and only then offer anything. The state is judged against the
   * plan version AND revision the request was made on, never against a revision number alone. */
  const checkState = useCallback(async (my: number, ctx: Ctx) => {
    setPhase("checking");
    const id = roundId!;
    const again: Pending = { kind: "unknown", ctx };
    let v: DeliveryView | null;
    try { v = await readView(id, my); } catch (e) {
      if (epoch.current !== my || unauthorized(e, my)) return;
      return settle({ tone: "warn", title: "Could not confirm",
        text: "Could not reach the server to see whether the recalculation started. It may or may not have. Nothing else will be sent, and nothing new can be started until your route can be read; check again when you are connected." },
        "idle", again);
    }
    if (epoch.current !== my) return;
    if (!v) {
      return settle({ tone: "warn", title: "Could not confirm",
        text: "Your route could not be read just now, so it is not known whether the recalculation started. Check again in a moment." }, "idle", again);
    }
    const running = v.reroute?.in_progress_run_id;
    // A run found while the request's own answer is missing: it may be that request's or another screen's, so it is followed as discovered.
    if (running) return void (await follow(running, my, { ...ctx, attribution: "discovered" }));
    const verdict = judgeState(ctx, v);
    if (verdict.kind === "replaced") {
      return settle({ tone: "warn", ...replacedText(ctx.attribution === "requested" ? "unanswered" : "discovered", verdict.was, verdict.now) });
    }
    if (verdict.kind === "changed") {
      return settle({ tone: "ok", title: "Your route was recalculated",
        text: `Your saved route is now revision ${verdict.revision}, recalculated from ${verdict.label} at ${clock(verdict.at)}. It was made after your request, but because the answer was lost it cannot be matched to it exactly.` });
    }
    if (verdict.kind === "unknown") {
      return settle({ tone: "warn", title: "Could not confirm",
        text: "Your route could not be compared with what you were looking at, so it is not known whether the recalculation started. Check again in a moment." }, "idle", again);
    }
    settle({ tone: "warn", title: "Nothing was recalculated",
      text: "No recalculation is running and your saved route is unchanged. Choose a starting point to try again." });
  }, [roundId, readView, follow, settle]);
  checkStateRef.current = checkState;

  /** The rider tapped an origin. Refused here (not only on the buttons) while anything about the server state is unresolved. */
  const start = useCallback(async (kind: OriginKind, orderId?: string) => {
    const v = viewRef.current;
    const exp = v ? expectedOf(v) : null;
    if (lock.current || pending.current || !roundId || !v?.reroute || !exp) return;
    lock.current = true;
    const my = epoch.current;
    const ctx: Ctx = { planVersion: exp.plan, revision: exp.revision, attribution: "requested" };
    setResult(null); setProblem(null);
    let fix: Fix | null = null;
    if (kind === "current_position") {
      setPhase("locating");
      const controller = new AbortController();
      ac.current = controller;
      try {
        fix = await readCurrentPosition(v.reroute.gps_limits, { signal: controller.signal });
      } catch (e) {
        if (epoch.current !== my) return;
        lock.current = false; ac.current = null; setPhase("choosing");
        if (e instanceof PositionError) setProblem(e.message);   // a cancel (AbortError) just returns to the choices
        return;
      }
      if (epoch.current !== my) return;
    }
    setPhase("submitting");
    try {
      const run = await api<RerouteRun>(`/api/rider/rounds/${roundId}/reroute`, {
        method: "POST", json: originBody(kind, exp, { fix: fix ?? undefined, orderId }),
      });
      fix = null;  // the position was used once; nothing keeps it
      if (epoch.current !== my) return;
      await follow(run.id, my, ctx);
    } catch (e) {
      fix = null;
      if (epoch.current !== my || unauthorized(e, my)) return;
      if (e instanceof ApiError && (isDefiniteRefusal(e) || e.code !== undefined)) {
        // The API itself said no, before starting anything: the route is untouched.
        const refusal = describeRefusal(e);
        // An existing run of the rider's own: its plan and who started it are not established, so it is followed as discovered.
        if (refusal.followRun) return void (await follow(refusal.followRun, my, ctxFromView(viewRef.current, "discovered")));
        let reloaded = !refusal.reload;
        if (refusal.reload) { try { await readView(roundId, my); reloaded = true; } catch { /* keep the refusal text */ } }
        if (epoch.current !== my) return;
        return settle({ tone: refusal.tone, title: "Not started", text: refusal.text + (reloaded ? "" : " Refresh to check your current route.") },
          refusal.retry ? "choosing" : "idle");
      }
      // No usable answer: the request may have reached the server. Read before offering another.
      await checkState(my, ctx);
    }
  }, [roundId, follow, checkState, readView, settle]);

  /** Read-only follow-ups for anything unresolved, in the context the request or run was made in (never recomputed from the
   * screen as it is now). They never send a recalculation. */
  const checkAgain = useCallback(async () => {
    const p = pending.current;
    if (lock.current || !roundId || !p) return;
    lock.current = true;
    const my = epoch.current;
    setResult(null);
    if (p.kind === "run") return void (await follow(p.runId, my, p.ctx));
    if (p.kind === "confirm") return void (await confirmSaved(roundId, my, p.run, p.ctx));
    await checkState(my, p.ctx);
  }, [roundId, follow, confirmSaved, checkState]);

  const cancelLocating = useCallback(() => { ac.current?.abort(); }, []);
  const open = useCallback(() => { if (!lock.current && !pending.current) { setResult(null); setProblem(null); setPhase("choosing"); } }, []);
  const close = useCallback(() => { if (!lock.current) { setProblem(null); setPhase("idle"); } }, []);
  /** The rider dismisses the MESSAGE. What is unresolved stays unresolved (see `Pending`). */
  const dismiss = useCallback(() => { if (!lock.current) setResult(null); }, []);
  /** A confirmed status change retires an old message about the route as it was, but never one that is still unresolved. */
  const retire = useCallback(() => { if (!lock.current && !pending.current) setResult(null); }, []);

  // A round change, navigation or sign-out drops everything in flight and forgets what was shown.
  useEffect(() => {
    epoch.current += 1;
    lock.current = false;
    followed.current = new Set();
    pending.current = null;
    setPhase("idle"); setResult(null); setProblem(null); setUnresolved(null);
    return () => { epoch.current += 1; ac.current?.abort(); ac.current = null; lock.current = false; };
  }, [roundId]);

  // A page refresh (or a second tab) may already have a run of the rider's own: follow it, never start another.
  const runningId = view?.round_id === roundId ? view?.reroute?.in_progress_run_id ?? null : null;
  useEffect(() => {
    if (!runningId || lock.current || followed.current.has(runningId)) return;
    lock.current = true;
    void follow(runningId, epoch.current, ctxFromView(viewRef.current, "discovered"));
  }, [runningId, follow]);

  const busy = BUSY.includes(phase);
  const canStart = !busy && online && !statusBusy;
  return { phase, busy, canStart, result, problem, unresolved, start, open, close, dismiss, retire, cancelLocating, checkAgain };
}

export type Reroute = ReturnType<typeof useReroute>;
