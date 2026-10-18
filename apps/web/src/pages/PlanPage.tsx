import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api, ApiError, type AdminOrder, type Mode, type Plan, type PlanningRun, type PlanVersion, type Readiness } from "../api";
import PlanView from "../components/PlanView";
import { card, Message, primaryButton, RoundPicker, secondaryButton, type Note } from "../components/ui";
import { FIX, isTerminal, km, pollRun, RUN_STATE_LABEL } from "../planning";
import { useErrorHandler, useRounds } from "../useRounds";

const MODES: { mode: Mode; title: string; text: string }[] = [
  { mode: "smart", title: "Smart", text: "Shortest total road distance within each rider's capacity." },
  { mode: "equal", title: "Equal", text: "Near-equal order counts within capacity. Not guaranteed: if the time-limited search misses it, the plan says so." },
  { mode: "manual", title: "Manual", text: "You lock an owner on every Pending order (bulk owner assignment on Orders); only the order of stops is optimized." },
];

type Refusal = { code?: string; message: string; details: string[] } | null;

export default function PlanPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const handle = useErrorHandler(onUnauthorized, setError, "Could not load planning.");
  const { rounds, roundId, select } = useRounds(handle);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [orders, setOrders] = useState<Record<string, AdminOrder>>({});
  const [plan, setPlan] = useState<Plan | null | undefined>(undefined);
  const [history, setHistory] = useState<PlanVersion[]>([]);
  const [viewing, setViewing] = useState<Plan | null>(null);
  const [run, setRun] = useState<PlanningRun | null>(null);
  const [refusal, setRefusal] = useState<Refusal>(null);
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  // At most one mode save per round (round id → the mode shown meanwhile). Switching rounds does
  // not clear it, so coming back keeps that round's controls disabled until the save and the
  // reload after it finish; other rounds stay usable.
  const [modeSaves, setModeSaves] = useState<Record<string, Mode>>({});
  const modeSavesRef = useRef(modeSaves);
  const setModeSave = useCallback((id: string, mode: Mode | null) => {
    const next = { ...modeSavesRef.current };
    if (mode) next[id] = mode; else delete next[id];
    modeSavesRef.current = next;
    setModeSaves(next);
  }, []);
  // Responses for a round that is no longer selected are dropped (round switching), and so is
  // any load that a later load (or a mode save) has superseded.
  const current = useRef<string | null>(null);
  current.current = roundId;
  const loadSeq = useRef(0);
  const refreshAc = useRef<AbortController | null>(null);

  const loadPlans = useCallback(async (id: string, signal?: AbortSignal, withRun = false) => {
    if (current.current !== id) return;  // e.g. a mode save that finished after a round switch
    const seq = ++loadSeq.current;
    const [r, o, h, runs] = await Promise.all([
      api<Readiness>(`/api/admin/rounds/${id}/readiness`, { signal }),
      api<AdminOrder[]>(`/api/admin/rounds/${id}/orders`, { signal }),
      api<PlanVersion[]>(`/api/admin/rounds/${id}/plans`, { signal }),
      withRun ? api<PlanningRun[]>(`/api/admin/rounds/${id}/planning-runs`, { signal }) : null,
    ]);
    const p = h.some((v) => v.is_current) ? await api<Plan>(`/api/admin/rounds/${id}/plan`, { signal }) : null;
    if (signal?.aborted || current.current !== id || seq !== loadSeq.current) return;
    setReadiness(r); setOrders(Object.fromEntries(o.map((x) => [x.id, x]))); setHistory(h); setPlan(p); setCheckedAt(new Date());
    // A polled run that already finished is never set back to an older, unfinished snapshot.
    if (runs) setRun((prev) => { const next = runs[0] ?? null; return prev && next && prev.id === next.id && isTerminal(prev.state) && !isTerminal(next.state) ? prev : next; });
  }, []);

  /** Reload readiness, orders, plans and the latest run for one round. A newer refresh or a
   * round switch aborts an unfinished one. */
  const refresh = useCallback(async (id: string) => {
    refreshAc.current?.abort();
    const ac = new AbortController();
    refreshAc.current = ac;
    setRefreshing(true);
    try {
      await loadPlans(id, ac.signal, true);
    } catch (e) {
      if (!ac.signal.aborted) handle(e);
    } finally {
      if (refreshAc.current === ac) { refreshAc.current = null; setRefreshing(false); }
    }
  }, [loadPlans, handle]);

  useEffect(() => {
    if (!roundId) return;
    setReadiness(null); setPlan(undefined); setHistory([]); setViewing(null); setRun(null); setRefusal(null); setNote(null); setError(null); setCheckedAt(null);
    refresh(roundId);
    return () => { refreshAc.current?.abort(); refreshAc.current = null; setRefreshing(false); };
  }, [roundId, refresh]);

  // Riders confirm in their own sessions: refresh when the admin comes back to this tab or
  // window. Event-driven only; nothing polls while the page is idle.
  useEffect(() => {
    if (!roundId) return;
    const id = roundId;
    const onFocus = () => {
      if (document.visibilityState !== "visible" || refreshAc.current || id in modeSavesRef.current) return;
      refresh(id);
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => { window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onFocus); };
  }, [roundId, refresh]);

  // Bounded polling of an unfinished run. Stops on a terminal state, on round switch or
  // navigation (abort), on session expiry (401 → sign-in) and after the time budget.
  const activeRunId = run && !isTerminal(run.state) ? run.id : null;
  useEffect(() => {
    if (!activeRunId || !roundId) return;
    const ac = new AbortController();
    const id = roundId;
    pollRun(activeRunId, {
      signal: ac.signal,
      onUpdate: (r) => { if (current.current === id && r.round_id === id) setRun(r); },
    }).then(async (res) => {
      // Not tied to this effect's signal: reaching a terminal state ends the effect itself.
      if (res.kind === "done") await loadPlans(id);
      if (res.kind === "timeout" && current.current === id) setNote({ kind: "warn", text: "The run is still going after several minutes. Reload this page later to see its result." });
    }).catch(handle);
    return () => ac.abort();
  }, [activeRunId, roundId, loadPlans, handle]);

  async function optimize() {
    if (!roundId) return;
    const id = roundId;
    setBusy(true); setRefusal(null); setNote(null);
    try {
      const r = await api<PlanningRun>(`/api/admin/rounds/${id}/optimize`, { method: "POST" });
      if (current.current === id) { setRun(r); setViewing(null); }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return onUnauthorized();
      if (current.current !== id) return;
      setRefusal(e instanceof ApiError ? { code: e.code, message: e.message, details: e.details } : { message: "Could not start planning.", details: [] });
      if (e instanceof ApiError && e.code === "RUN_IN_PROGRESS") {
        api<PlanningRun[]>(`/api/admin/rounds/${id}/planning-runs`).then((runs) => { if (current.current === id) setRun(runs[0] ?? null); }).catch(handle);
      }
      loadPlans(id).catch(handle);
    } finally {
      setBusy(false);
    }
  }

  async function setMode(mode: Mode) {
    if (!roundId || !readiness || roundId in modeSavesRef.current || readiness.mode === mode) return;
    const id = roundId, before = readiness.mode;
    setModeSave(id, mode);  // shown at once, with the mode controls and Optimize disabled
    setNote(null); setRefusal(null);
    loadSeq.current++;  // loads already in flight predate this change and are dropped
    let failure: string | null = null;
    try {
      await api(`/api/admin/rounds/${id}/mode`, { method: "PUT", json: { mode } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setModeSave(id, null); return onUnauthorized(); }
      failure = e instanceof ApiError ? e.message.replace(/\.?$/, ".") : "The server could not be reached.";
      setModeSave(id, before);
    }
    try {
      await loadPlans(id);  // the server's state, after success or failure
    } catch (e) {
      handle(e);
    } finally {
      setModeSave(id, null);
    }
    if (current.current !== id) return;
    setNote(failure
      ? { kind: "error", text: `The mode was not changed: ${failure} The mode shown is the one saved on the server.` }
      : { kind: "ok", text: `Mode set to ${mode}.` });
  }

  async function view(version: number) {
    if (!roundId) return;
    const id = roundId;
    try {
      const p = await api<Plan>(`/api/admin/rounds/${id}/plans/${version}`);
      if (current.current === id) setViewing(p);
    } catch (e) { handle(e); }
  }

  if (rounds === null) return error ? <p role="alert" className="text-red-800">{error}</p> : <p role="status" className="text-slate-500">Loading…</p>;
  if (rounds.length === 0) {
    return <p className="rounded-xl bg-white p-6 text-slate-600 ring-1 ring-slate-200">No rounds yet. <Link className="font-medium text-brand-700 underline" to="/admin/import">Import an Excel file</Link> first.</p>;
  }

  const running = run !== null && !isTerminal(run.state);
  const r = readiness;
  const limits = r?.planning_limits;
  const tooMany = r && limits ? r.pending_orders > limits.max_pending_orders : false;
  const tooManyRiders = r && limits ? r.riders.participating > limits.max_riders : false;
  const reasons: string[] = [];
  if (r) {
    if (!r.ready) reasons.push("finish the readiness checklist");
    if (r.pending_orders === 0) reasons.push("there are no Pending orders");
    if (tooMany || tooManyRiders) reasons.push("the round is larger than the per-run limits");
  }
  if (running) reasons.push("a run is in progress");
  const pendingMode = roundId ? modeSaves[roundId] : undefined;
  const savingMode = pendingMode !== undefined;
  if (savingMode) reasons.push("the distribution mode is being saved");
  const canOptimize = !!r && reasons.length === 0 && !busy;
  const shownMode = pendingMode ?? r?.mode;
  const failed = run && isTerminal(run.state) && run.state !== "succeeded" ? run : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">Plan routes</h1>
        <RoundPicker rounds={rounds} roundId={roundId} onSelect={select} />
        <button type="button" className={secondaryButton} disabled={!roundId || refreshing || savingMode}
          onClick={() => roundId && refresh(roundId)}>Refresh readiness</button>
      </div>
      <p role="status" className="-mt-2 text-xs text-slate-600" data-testid="refresh-status">
        {refreshing ? "Checking the latest readiness, plans and run…" : checkedAt ? `Readiness checked at ${checkedAt.toLocaleTimeString()}. Riders confirm in their own sessions; refresh to see their changes.` : ""}
      </p>
      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {!r ? <p role="status" className="text-slate-500">Loading round…</p> : (
        <>
          <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
            <section className={card} aria-labelledby="readiness-title" data-testid="readiness-checklist">
              <h2 id="readiness-title" className="mb-2 text-lg font-semibold">Readiness</h2>
              <ul className="space-y-2 text-sm">
                <Check ok={r.orders_ready} text={r.orders_ready ? `All ${r.orders} orders have a valid pin` : `${r.blockers.length} of ${r.orders} orders need a valid pin`}>
                  {r.blockers.length > 0 && <ul className="mt-1 list-disc pl-5">{r.blockers.map((b) => <li key={b.order_code}>{b.order_code}: {b.reason}</li>)}</ul>}
                  {!r.orders_ready && <Link className="font-medium text-brand-700 underline" to={`/admin?round=${roundId}`}>Fix pins on Orders</Link>}
                </Check>
                <Check ok={r.pending_orders > 0 && !tooMany} text={`${r.pending_orders} Pending order(s) to plan (limit ${limits!.max_pending_orders} per run)`} />
                <Check ok={r.configuration_blockers.length === 0 && !tooManyRiders}
                  text={`${r.riders.participating} participating rider(s), ${r.riders.confirmed} confirmed (limit ${limits!.max_riders} per run)`}>
                  {r.configuration_blockers.length > 0 && (
                    <ul className="mt-1 list-disc pl-5" data-testid="configuration-blockers">
                      {r.configuration_blockers.map((b, i) => <li key={`${b.code}-${b.rider_id ?? i}`}>{b.reason}</li>)}
                    </ul>
                  )}
                  {r.configuration_blockers.length > 0 && <Link className="font-medium text-brand-700 underline" to={`/admin/round?round=${roundId}`}>Open Round setup</Link>}
                </Check>
              </ul>
              <p className="mt-3 text-xs text-slate-600" data-testid="limits">
                Limits on this server: up to {limits!.max_pending_orders} Pending orders, {limits!.max_riders} riders and {limits!.max_locations} distinct
                road points (orders, starts and destinations) per run. Each of up to three solver attempts stops after {limits!.solve_seconds} s, so
                large rounds can take a minute or more.
              </p>
            </section>

            <section className={card} aria-labelledby="mode-title">
              <h2 id="mode-title" className="mb-2 text-lg font-semibold">Distribution mode</h2>
              <fieldset disabled={running || savingMode} aria-describedby="mode-status">
                <legend className="sr-only">Distribution mode</legend>
                <div className="space-y-2">
                  {MODES.map((m) => (
                    <label key={m.mode} className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-lg p-3 ring-1 ${shownMode === m.mode ? "bg-brand-600/5 ring-brand-600" : "ring-slate-200"}`}>
                      <input type="radio" name="mode" value={m.mode} checked={shownMode === m.mode} onChange={() => setMode(m.mode)} className="mt-1 size-5" />
                      <span><span className="font-medium">{m.title}</span><span className="block text-xs text-slate-600">{m.text}</span></span>
                    </label>
                  ))}
                </div>
                <p id="mode-status" role="status" className="mt-2 text-sm text-slate-600" data-testid="mode-status">{savingMode ? "Saving the distribution mode…" : ""}</p>
              </fieldset>
              <div className="mt-4 space-y-2">
                <button type="button" className={`${primaryButton} w-full sm:w-auto`} disabled={!canOptimize} onClick={optimize}
                  aria-describedby="optimize-why">{running ? "Planning…" : "Optimize routes"}</button>
                <p id="optimize-why" className="text-sm text-slate-600" data-testid="optimize-why">
                  {reasons.length ? `Optimize is unavailable: ${reasons.join("; ")}.` : "Ready. Optimizing uses road distances from the local routing engine."}
                </p>
              </div>
            </section>
          </div>

          <Message note={note} />
          {refusal && (
            <div role="alert" data-testid="refusal" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-900 ring-1 ring-red-200">
              <p className="font-semibold">Planning was not started{refusal.code ? ` (${refusal.code})` : ""}: {refusal.message}</p>
              {refusal.details.length > 0 && <ul className="mt-1 list-disc pl-5">{refusal.details.map((d) => <li key={d}>{d}</li>)}</ul>}
              {refusal.code && FIX[refusal.code] && <p className="mt-1">{FIX[refusal.code]}</p>}
              <p className="mt-1">Nothing was saved{plan ? `; the current plan (version ${plan.version}) is unchanged` : ""}.</p>
            </div>
          )}
          {run && <RunPanel run={run} plan={plan ?? null} />}

          {viewing ? (
            <div className="space-y-3">
              <button type="button" className={secondaryButton} onClick={() => setViewing(null)}>Back to the current plan</button>
              <PlanView plan={viewing} orders={orders} title={viewing.is_current ? "Current plan" : `History: version ${viewing.version}`} />
            </div>
          ) : plan === undefined ? <p role="status" className="text-slate-500">Loading plan…</p> : plan === null ? (
            <p className={`${card} text-slate-600`} data-testid="no-plan">No plan has been saved for this round yet.</p>
          ) : (
            <PlanView plan={plan} orders={orders}
              title={running ? "Current plan (previous result; a new run is in progress)" : failed ? "Current plan (the latest run did not replace it)" : "Current plan"} />
          )}

          {history.length > 0 && (
            <section className={card} aria-labelledby="history-title" data-testid="plan-history">
              <h2 id="history-title" className="mb-2 text-lg font-semibold">Version history</h2>
              <ul className="divide-y divide-slate-100 text-sm">
                {history.map((v) => (
                  <li key={v.version} className="flex flex-wrap items-center gap-2 py-2">
                    <span className="font-semibold">Version {v.version}</span>
                    <span className="text-slate-600">{new Date(v.created_at).toLocaleString()} · {v.mode} · {v.planned_orders ?? 0} orders · {v.total_road_distance_m != null ? km(v.total_road_distance_m) : "—"}</span>
                    {v.is_current && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-900">Current</span>}
                    {v.out_of_date && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900">Out of date</span>}
                    {v.progress_since_plan && <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-900">Deliveries updated</span>}
                    <button type="button" className={`${secondaryButton} ml-auto`} onClick={() => view(v.version)}
                      aria-label={`View version ${v.version}`}>View</button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Check({ ok, text, children }: { ok: boolean; text: string; children?: ReactNode }) {
  return (
    <li className="flex gap-2" data-testid="check" data-ok={ok}>
      <span aria-hidden className={`mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${ok ? "bg-emerald-600" : "bg-amber-500"}`}>{ok ? "✓" : "!"}</span>
      <div className="min-w-0"><p><span className="sr-only">{ok ? "Done: " : "To do: "}</span>{text}</p>{children}</div>
    </li>
  );
}

function RunPanel({ run, plan }: { run: PlanningRun; plan: Plan | null }) {
  const requested = new Date(run.requested_at).toLocaleTimeString();
  if (!isTerminal(run.state)) {
    return (
      <div role="status" data-testid="run-status" data-state={run.state} className="rounded-lg bg-sky-50 px-4 py-3 text-sm text-sky-950 ring-1 ring-sky-200">
        <p className="font-semibold"><span className="mr-2 inline-block size-3 animate-pulse rounded-full bg-sky-600" aria-hidden />{RUN_STATE_LABEL[run.state]}…</p>
        <p>Requested at {requested} in {run.mode} mode. The run continues on the server if you leave this page.</p>
      </div>
    );
  }
  if (run.state === "succeeded") {
    const t = run.timings;
    return (
      <div role="status" data-testid="run-status" data-state={run.state} className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-950 ring-1 ring-emerald-200">
        <p className="font-semibold">Latest run (requested {requested}): plan version {run.plan_version} saved.</p>
        {t && <p className="text-xs">Road matrices {Number(t.matrix_s ?? 0).toFixed(1)} s, solving {Number(t.solve_s ?? 0).toFixed(1)} s.</p>}
      </div>
    );
  }
  const code = run.error?.code;
  return (
    <div role="alert" data-testid="run-status" data-state={run.state} className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-900 ring-1 ring-red-200">
      <p className="font-semibold">Latest run (requested {requested}): {RUN_STATE_LABEL[run.state]}.</p>
      {run.error && <p>{run.error.message}</p>}
      {run.error && run.error.details.length > 0 && <ul className="mt-1 list-disc pl-5">{run.error.details.map((d) => <li key={d}>{d}</li>)}</ul>}
      {code && FIX[code] && <p className="mt-1">{FIX[code]}</p>}
      <p className="mt-1">{plan ? `The plan below is still version ${plan.version} from before this run; it was not replaced.` : "No plan has been saved for this round."}</p>
    </div>
  );
}
