import { KIND_LABEL, type DeliveryView } from "../api";
import { awaitingText, locationSupport, pendingCount, POSITION_TEXT } from "../reroute";
import type { Reroute } from "../useReroute";
import { card, primaryButton, secondaryButton } from "./ui";

// Step 4D: "Recalculate my route", a section of its own (the Route card is not touched). It re-orders only the
// rider's own remaining Pending deliveries through the existing rider-only API. Nothing happens by itself:
// a postponed customer, a changed destination or an order outside the saved route only OFFER it. Every
// starting point is a button the rider taps; none is preselected, remembered or used as a silent fallback.

const optionButton = "flex min-h-14 w-full flex-col items-start justify-center gap-0.5 rounded-lg px-4 py-2 text-left disabled:cursor-not-allowed disabled:opacity-60";

const TONE = {
  ok: "bg-emerald-50 text-emerald-950 ring-emerald-300",
  warn: "bg-amber-50 text-amber-950 ring-amber-300",
  error: "bg-red-50 text-red-900 ring-red-200",
};

const PROGRESS: Record<string, string> = {
  locating: "Getting your location… allow location access if your browser asks.",
  submitting: "Sending your request…",
  running: "Recalculating your route. This needs a connection. Status and setup changes wait until it finishes.",
  checking: "Checking your route on the server…",
  finishing: "Loading your new route…",
};

export default function RerouteSection({ view, rr, online, statusBusy, postponed, onKeep }: {
  view: DeliveryView; rr: Reroute; online: boolean; statusBusy: boolean;
  postponed: string | null;     // the order code just saved as Postponed (offer only, never automatic)
  onKeep: () => void;
}) {
  const opts = view.reroute;
  if (!opts || !view.plan) return null;
  const pending = pendingCount(view);
  const awaiting = awaitingText(view);
  const support = locationSupport();
  const blocked = opts.blocked;
  const readOnly = rr.unresolved !== null;   // the server state is not established: read it before offering another request (the message may be dismissed; this stays)
  const canChoose = rr.canStart && opts.available && pending > 0 && !readOnly;
  const start = view.setup?.start;
  const startName = start ? (start.label && start.label !== KIND_LABEL[start.kind] ? `${KIND_LABEL[start.kind]} (${start.label})` : KIND_LABEL[start.kind]) : "your configured start";
  const last = opts.last_completed_stop;

  return (
    <section className={card} aria-labelledby="reroute-title" data-testid="reroute" data-phase={rr.phase} aria-busy={rr.busy}>
      <h3 id="reroute-title" className="text-lg font-semibold">Recalculate my route</h3>
      <p className="mt-1 text-sm text-slate-600">
        Re-orders only your own remaining Pending deliveries. Other riders' routes, your Postponed and Completed orders and who holds
        each order stay as they are. It needs a connection to the server; until a new route is saved, your current one stays shown.
      </p>

      {postponed && rr.phase === "idle" && (
        <div className="mt-3 rounded-lg bg-violet-50 p-3 text-sm text-violet-950 ring-1 ring-violet-300" role="status" data-testid="reroute-cue-postponed">
          <p><b>{postponed}</b> was saved as Postponed. Your saved order is unchanged, and nothing is recalculated unless you choose to.</p>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:flex">
            <button type="button" className={secondaryButton} onClick={onKeep} data-testid="reroute-keep">Keep current order</button>
            <button type="button" className={primaryButton} onClick={rr.open} disabled={!canChoose} data-testid="reroute-recalculate">Recalculate my route</button>
          </div>
        </div>
      )}
      {view.unsequenced.length > 0 && (
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950 ring-1 ring-amber-300" data-testid="reroute-cue-unsequenced">
          {view.unsequenced.length === 1 ? "1 Pending order is" : `${view.unsequenced.length} Pending orders are`} not in your saved route (for example one you returned
          from Postponed). Recalculating places {view.unsequenced.length === 1 ? "it" : "them"}.
        </p>
      )}
      {awaiting && (
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950 ring-1 ring-amber-300" role="status" data-testid="reroute-cue-awaiting">
          {awaiting}{" "}
          {blocked?.code === "NOT_CONFIRMED" ? "Confirm your new setup above first, then recalculate." : "Recalculate to route to your new destination."}
        </p>
      )}

      {blocked && (
        <p className="mt-3 rounded-lg bg-slate-100 p-3 text-sm text-slate-800" data-testid="reroute-blocked" data-code={blocked.code}>{blocked.message}</p>
      )}
      {!blocked && pending === 0 && (
        <p className="mt-3 text-sm text-slate-700" data-testid="reroute-nothing">You have no Pending deliveries to recalculate.</p>
      )}
      {!online && (
        <p className="mt-3 rounded-lg bg-slate-100 p-3 text-sm text-slate-800" role="status" data-testid="reroute-offline">
          You are offline. Recalculating needs a connection to the server. Your saved route is unchanged and stays shown; nothing is queued.
        </p>
      )}

      {rr.busy && (
        <div className="mt-3 rounded-lg bg-sky-50 p-3 text-sm text-sky-950 ring-1 ring-sky-200" role="status" data-testid="reroute-progress" data-phase={rr.phase}>
          <p>{PROGRESS[rr.phase]}</p>
          {rr.phase === "locating" && (
            <button type="button" className={`${secondaryButton} mt-2 bg-white`} onClick={rr.cancelLocating} data-testid="reroute-cancel">Cancel</button>
          )}
        </div>
      )}

      {rr.result && (
        <div className={`mt-3 rounded-lg p-3 text-sm ring-1 ${TONE[rr.result.tone]}`} role={rr.result.tone === "error" ? "alert" : "status"} data-testid="reroute-result" data-tone={rr.result.tone}>
          <p className="font-semibold">{rr.result.title}</p>
          <p className="mt-0.5">{rr.result.text}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {rr.unresolved && <CheckAgain rr={rr} online={online} />}
            <button type="button" className={`${secondaryButton} bg-white`} onClick={rr.dismiss} disabled={rr.busy}>Dismiss</button>
          </div>
        </div>
      )}
      {!rr.result && rr.unresolved && !rr.busy && (
        <div className={`mt-3 rounded-lg p-3 text-sm ring-1 ${TONE.warn}`} role="status" data-testid="reroute-unresolved" data-kind={rr.unresolved.kind}>
          <p className="font-semibold">Your route is not confirmed</p>
          <p className="mt-0.5">
            The server has not confirmed what happened to your recalculation, so nothing new can be started yet. Your previous route is still shown.
            Check again to read it from the server.
          </p>
          <div className="mt-2"><CheckAgain rr={rr} online={online} /></div>
        </div>
      )}

      {rr.phase === "idle" && !postponed && !blocked && pending > 0 && !readOnly && (
        <button type="button" className={`${primaryButton} mt-3`} onClick={rr.open} disabled={!canChoose} data-testid="reroute-open">Recalculate my route…</button>
      )}

      {rr.phase === "choosing" && !rr.busy && (
        <div className="mt-3 space-y-3" data-testid="reroute-choices">
          <p className="text-sm font-semibold">Where should the new route start? Choose one; nothing is chosen for you.</p>
          {rr.problem && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-900 ring-1 ring-red-200" data-testid="reroute-problem">{rr.problem}</p>}
          <button type="button" className={`${optionButton} bg-brand-600 text-white hover:bg-brand-700`} disabled={!canChoose || support !== "ok"}
            onClick={() => void rr.start("current_position")} data-testid="reroute-current">
            <span className="font-semibold">Use my current location</span>
            <span className="text-sm font-normal">Asks your phone for one position now. It is used once and never stored.</span>
          </button>
          {support !== "ok" && (
            <p className="rounded-lg bg-slate-100 p-3 text-sm text-slate-800" data-testid="reroute-support" data-support={support}>{POSITION_TEXT[support]}</p>
          )}
          {last && (
            <button type="button" className={`${optionButton} bg-white ring-1 ring-slate-400 hover:bg-slate-50`} disabled={!canChoose}
              onClick={() => void rr.start("last_completed_stop", last.order_id)} data-testid="reroute-last">
              <span className="font-semibold">From my last completed stop: {last.order_code} ({last.customer_name})</span>
              <span className="text-sm font-normal text-slate-700">Not your current position: the route is calculated as if you were still at that stop.</span>
            </button>
          )}
          {opts.configured_start_allowed && (
            <button type="button" className={`${optionButton} bg-white ring-1 ring-slate-400 hover:bg-slate-50`} disabled={!canChoose}
              onClick={() => void rr.start("configured_start")} data-testid="reroute-start">
              <span className="font-semibold">From the {startName} (my configured start)</span>
              <span className="text-sm font-normal text-slate-700">Not your current position: the route is calculated as if you were starting from there.</span>
            </button>
          )}
          <button type="button" className={secondaryButton} onClick={rr.close} data-testid="reroute-close">Close</button>
        </div>
      )}
      {!canChoose && !rr.busy && rr.phase === "choosing" && statusBusy && (
        <p className="mt-2 text-sm text-slate-600">Waiting for a status change to finish saving…</p>
      )}
    </section>
  );
}

/** The read-only follow-up for anything unresolved: it reads the server (never sends a recalculation). */
function CheckAgain({ rr, online }: { rr: Reroute; online: boolean }) {
  return (
    <button type="button" className={`${secondaryButton} bg-white`} onClick={() => void rr.checkAgain()} disabled={!online || rr.busy} data-testid="reroute-check-again">
      {rr.unresolved?.kind === "run" ? "Check the recalculation again" : "Check my route again"}
    </button>
  );
}
