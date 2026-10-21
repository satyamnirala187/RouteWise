import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, DESTINATION_KINDS, KIND_LABEL, PRIVATE_KINDS, VEHICLE_LABEL, type DestinationKind, type RiderSetup } from "../api";
import { COORD_HELP, ConfirmationBadge, inputClass, Message, parseCoords, primaryButton, secondaryButton, type Note } from "./ui";

const HINT: Record<DestinationKind, string> = {
  office: "Return to the Office after your last delivery.",
  warehouse: "Return to the Warehouse after your last delivery.",
  home: "Finish at your home. Only you can see this location.",
  last_stop: "Finish at your final delivery; no return trip is planned.",
  custom: "Finish at another place. Only you can see this location.",
};

const STATE_TEXT = {
  confirmed: "You confirmed this setup. Any later change to it will ask you to confirm again.",
  not_confirmed: "Not confirmed yet. Saving a destination is not a confirmation — confirm the setup below.",
  outdated: "Your setup changed after you confirmed it (start, vehicle, capacity, destination or a depot location). Review it and confirm again.",
};

/** One round's setup for the signed-in rider: choose a destination, save it, then confirm the
 * whole setup version shown. Coordinates stay in component state only. */
export default function DestinationCard({ roundId, roundName, onUnauthorized, onChanged, disabled = false }: {
  roundId: string; roundName: string; onUnauthorized: () => void;
  onChanged?: () => void;  // after a save, confirm or reload, e.g. to refresh the delivery view
  disabled?: boolean;      // 4D: the rider's route is being recalculated; setup changes wait so the run cannot go stale
}) {
  const [setup, setSetup] = useState<RiderSetup | null>(null);
  const [kind, setKind] = useState<DestinationKind | "">("");
  const [coords, setCoords] = useState("");
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState(false);  // a confirmed round shows its summary until the rider asks to change it

  const adopt = useCallback((s: RiderSetup) => {
    setSetup(s);
    setKind(s.destination?.kind ?? "");
    setCoords(s.destination && PRIVATE_KINDS.includes(s.destination.kind) && s.destination.lat != null
      ? `${s.destination.lat}, ${s.destination.lng}` : "");
  }, []);

  const load = useCallback((signal?: AbortSignal) =>
    api<RiderSetup>(`/api/rider/rounds/${roundId}`, { signal }).then((s) => { if (!signal?.aborted) adopt(s); }), [roundId, adopt]);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal).catch((e) => {
      if (ac.signal.aborted) return;
      if (e instanceof ApiError && e.status === 401) onUnauthorized();
      else setNote({ kind: "error", text: "Could not load this round." });
    });
    return () => ac.abort();
  }, [load, onUnauthorized]);

  async function act(fn: () => Promise<void>) {
    if (disabled) return;
    setBusy(true); setNote(null);
    try {
      await fn();
      onChanged?.();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return onUnauthorized();
      if (e instanceof ApiError && e.code === "configuration_changed") {
        await load().catch(() => undefined);  // show the current version before asking again
        onChanged?.();
        return setNote({ kind: "warn", text: e.message });
      }
      setNote({ kind: "error", text: e instanceof ApiError ? e.message : "Something went wrong.", details: e instanceof ApiError ? e.details : [] });
    } finally {
      setBusy(false);
    }
  }

  function save(e: FormEvent) {
    e.preventDefault();
    if (!kind) return setNote({ kind: "error", text: "Choose where your route should end." });
    let body: Record<string, unknown> = { kind };
    if (PRIVATE_KINDS.includes(kind)) {
      const c = parseCoords(coords);
      if (!c) return setNote({ kind: "error", text: "Enter the location as latitude, longitude (for example 28.7027, 77.1940)." });
      body = { kind, lat: c[0], lng: c[1] };
    }
    act(async () => {
      const s = await api<RiderSetup>(`/api/rider/rounds/${roundId}/destination`, { method: "PUT", json: body });
      adopt(s);
      setNote(s.confirmation.state === "confirmed"
        ? { kind: "ok", text: "Saved. Nothing changed, so your confirmation still stands." }
        : { kind: "warn", text: "Saved, not confirmed yet. Check the summary and confirm your setup." });
    });
  }

  function confirm() {
    if (!setup) return;
    act(async () => {
      const s = await api<RiderSetup>(`/api/rider/rounds/${roundId}/confirm`, { method: "POST", json: { config_version: setup.config_version } });
      adopt(s);
      setChanging(false);
      setNote({ kind: "ok", text: "Confirmed. Your admin can now plan this round." });
    });
  }

  if (!setup) {
    return <li className="rounded-xl bg-white p-4 ring-1 ring-slate-200"><p role="status" className="text-slate-500">Loading {roundName}…</p><Message note={note} /></li>;
  }

  const savedKind = setup.destination?.kind ?? "";
  const unsaved = kind !== savedKind || (PRIVATE_KINDS.includes(kind as DestinationKind) &&
    coords.replace(/\s/g, "") !== (setup.destination?.lat != null ? `${setup.destination.lat},${setup.destination.lng}` : ""));
  const d = setup.destination;
  const canConfirm = setup.issues.length === 0 && !unsaved && setup.confirmation.state !== "confirmed";
  const name = `destination-${roundId}`;

  return (
    <li className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="destination-card" data-round={roundId}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="mr-auto font-semibold">{setup.round_name}</h3>
        <ConfirmationBadge state={setup.confirmation.state} />
      </div>
      <p className="mt-1 text-sm text-slate-700" data-testid="confirmation-text">{STATE_TEXT[setup.confirmation.state]}</p>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid="setup-summary">
        <dt className="text-slate-500">Start</dt>
        <dd>{KIND_LABEL[setup.start.kind]}{setup.start.label && setup.start.label !== KIND_LABEL[setup.start.kind] ? ` — ${setup.start.label}` : ""}{!setup.start.set && " (not set yet)"}</dd>
        <dt className="text-slate-500">Vehicle</dt><dd>{VEHICLE_LABEL[setup.vehicle]}</dd>
        <dt className="text-slate-500">Capacity</dt><dd>{setup.capacity} orders</dd>
        <dt className="text-slate-500">Destination</dt>
        <dd>
          {d ? KIND_LABEL[d.kind] : "Not chosen yet"}
          {d && (d.kind === "office" || d.kind === "warehouse") && d.label && d.label !== KIND_LABEL[d.kind] ? ` — ${d.label}` : ""}
          {d && PRIVATE_KINDS.includes(d.kind) && d.lat != null && <span className="text-slate-600"> ({d.lat}, {d.lng}; only you can see this)</span>}
          {d?.kind === "last_stop" && <span className="text-slate-600"> (open route)</span>}
        </dd>
      </dl>
      {setup.issues.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-amber-900">{setup.issues.map((i) => <li key={i.code}>{i.reason}</li>)}</ul>
      )}

      {setup.confirmation.state === "confirmed" && !changing ? (
        <button type="button" className={`${secondaryButton} mt-3`} disabled={disabled} onClick={() => { setChanging(true); setNote(null); }}>Change destination</button>
      ) : (
      <form onSubmit={save} className="mt-4 space-y-3 border-t border-slate-100 pt-3">
        <fieldset>
          <legend className="text-sm font-semibold">Where should your route end?</legend>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {DESTINATION_KINDS.map((k) => (
              <label key={k} className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-lg p-3 ring-1 ${kind === k ? "bg-brand-600/5 ring-brand-600" : "ring-slate-200"}`}>
                <input type="radio" name={name} value={k} checked={kind === k} onChange={() => setKind(k)} className="mt-1 size-5" />
                <span><span className="font-medium">{KIND_LABEL[k]}</span><span className="block text-xs text-slate-600">{HINT[k]}</span></span>
              </label>
            ))}
          </div>
        </fieldset>
        {kind && PRIVATE_KINDS.includes(kind) && (
          <label className="block text-sm font-medium">{KIND_LABEL[kind]} location (latitude, longitude)
            <input className={inputClass} value={coords} onChange={(e) => setCoords(e.target.value)} inputMode="decimal"
              placeholder="28.7027, 77.1940" aria-describedby={`${name}-help`} autoComplete="off" />
            <span id={`${name}-help`} className="mt-1 block text-xs font-normal text-slate-600">{COORD_HELP}</span>
          </label>
        )}
        <div className="flex flex-wrap gap-2">
          <button disabled={busy || disabled || !kind} className={secondaryButton}>Save destination</button>
          <button type="button" disabled={busy || disabled || !canConfirm} onClick={confirm} className={primaryButton}
            aria-describedby={`${name}-confirm-help`}>Confirm this setup</button>
        </div>
        <p id={`${name}-confirm-help`} className="text-xs text-slate-600">
          {setup.confirmation.state === "confirmed" && !unsaved ? "Already confirmed." :
            unsaved ? "Save your destination first, then confirm." :
            setup.issues.length > 0 ? "Resolve the items above before confirming." : "Confirming tells your admin this setup is correct."}
        </p>
      </form>
      )}
      {disabled && <p className="mt-2 text-sm text-slate-600" data-testid="setup-waits">Setup changes wait while your route is being recalculated.</p>}
      <div className="mt-2"><Message note={note} /></div>
    </li>
  );
}
