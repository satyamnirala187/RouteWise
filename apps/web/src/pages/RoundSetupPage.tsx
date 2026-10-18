import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, ApiError, DEPOT_KINDS, VEHICLE_LABEL, type DepotKind, type Readiness, type RiderProfile, type RoundRider, type Vehicle } from "../api";
import { ConfirmationBadge, destinationLabel, inputClass, Message, primaryButton, RoundPicker, Section, secondaryButton, type Note } from "../components/ui";
import { useErrorHandler, useRounds } from "../useRounds";

const START_LABEL: Record<DepotKind, string> = { office: "Office", warehouse: "Warehouse" };

// Round → riders: participation, vehicle, capacity and start; destinations are shown by kind and
// confirmation state only. Riders choose and confirm their own destination on their phone.
export default function RoundSetupPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const handle = useErrorHandler(onUnauthorized, setError, "Could not load the round setup.");
  const { rounds, roundId, select } = useRounds(handle);
  const [riders, setRiders] = useState<RoundRider[] | null>(null);
  const [profiles, setProfiles] = useState<RiderProfile[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);

  const load = useCallback((id: string, signal?: AbortSignal) => {
    Promise.all([
      api<RoundRider[]>(`/api/admin/rounds/${id}/riders`, { signal }),
      api<RiderProfile[]>("/api/admin/riders", { signal }),
      api<Readiness>(`/api/admin/rounds/${id}/readiness`, { signal }),
    ]).then(([rr, p, r]) => {
      if (signal?.aborted) return;  // a newer round was selected meanwhile
      setRiders(rr); setProfiles(p); setReadiness(r); setError(null);
    }).catch(handle);
  }, [handle]);

  useEffect(() => {
    if (!roundId) return;
    setRiders(null); setReadiness(null);
    const ac = new AbortController();
    load(roundId, ac.signal);
    return () => ac.abort();
  }, [roundId, load]);

  const reload = useCallback(() => { if (roundId) load(roundId); }, [roundId, load]);

  if (rounds === null) return error ? <p role="alert" className="text-red-800">{error}</p> : <p role="status" className="text-slate-500">Loading…</p>;
  if (rounds.length === 0) {
    return <p className="rounded-xl bg-white p-6 text-slate-600 ring-1 ring-slate-200">No rounds yet. <Link className="font-medium text-brand-700 underline" to="/admin/import">Import an Excel file</Link> first.</p>;
  }

  const inRound = new Set(riders?.map((r) => r.rider_id) ?? []);
  const addable = profiles.filter((p) => p.account_active && !inRound.has(p.id));
  const participating = riders?.filter((r) => r.participating) ?? [];
  const others = riders?.filter((r) => !r.participating) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">Round setup</h1>
        <RoundPicker rounds={rounds} roundId={roundId} onSelect={select} />
      </div>
      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {readiness && (
        <p role="status" data-testid="setup-summary" className={`rounded-lg px-4 py-3 text-sm ring-1 ${readiness.configuration_blockers.length === 0 ? "bg-emerald-50 text-emerald-900 ring-emerald-200" : "bg-amber-50 text-amber-950 ring-amber-200"}`}>
          {readiness.riders.participating} participating, {readiness.riders.confirmed} confirmed.{" "}
          {readiness.configuration_blockers.length === 0 ? "Rider setup is complete." : `${readiness.configuration_blockers.length} item(s) still block planning.`}{" "}
          <Link className="font-medium underline" to={`/admin/plan?round=${roundId}`}>Open planning</Link>
        </p>
      )}
      <p className="text-sm text-slate-600">
        Each rider chooses and confirms their own destination in their app. You can see the destination type and whether it is
        confirmed, but never a rider's Home or Custom location. Any change to participation, vehicle, capacity or start asks that
        rider to confirm again.
      </p>
      {riders === null ? <p role="status" className="text-slate-500">Loading riders…</p> : (
        <>
          <Section title="Participating riders" testId="participating-riders">
            {participating.length === 0 ? <p className="text-slate-600">No rider takes part in this round yet. Add one below.</p> : (
              <ul className="space-y-3">
                {participating.map((r) => <RoundRiderRow key={`${roundId}-${r.rider_id}`} roundId={roundId!} rider={r}
                  onSaved={reload} onReload={reload} onUnauthorized={onUnauthorized} />)}
              </ul>
            )}
          </Section>
          {others.length > 0 && (
            <Section title="Not participating" testId="removed-riders">
              <ul className="space-y-3">
                {others.map((r) => <RoundRiderRow key={`${roundId}-${r.rider_id}`} roundId={roundId!} rider={r}
                  onSaved={reload} onReload={reload} onUnauthorized={onUnauthorized} />)}
              </ul>
            </Section>
          )}
          <AddRider key={roundId} roundId={roundId!} addable={addable} onAdded={reload} onUnauthorized={onUnauthorized} />
        </>
      )}
    </div>
  );
}

function RoundRiderRow({ roundId, rider, onSaved, onReload, onUnauthorized }: {
  roundId: string; rider: RoundRider; onSaved: () => void; onReload: () => void; onUnauthorized: () => void;
}) {
  const [vehicle, setVehicle] = useState<Vehicle>(rider.vehicle);
  const [capacity, setCapacity] = useState(String(rider.capacity));
  const [start, setStart] = useState<DepotKind>(rider.start);
  const [note, setNote] = useState<Note>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setVehicle(rider.vehicle); setCapacity(String(rider.capacity)); setStart(rider.start); }, [rider.config_version]);

  async function put(body: Record<string, unknown>, ok: string) {
    setBusy(true); setNote(null); setConflict(false);
    try {
      await api(`/api/admin/rounds/${roundId}/riders/${rider.rider_id}`, { method: "PUT", json: { version: rider.config_version, ...body } });
      setNote({ kind: "ok", text: ok });
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized();
      setConflict(err instanceof ApiError && err.status === 409);
      setNote({ kind: "error", text: err instanceof ApiError ? err.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  }

  function save(e: FormEvent) {
    e.preventDefault();
    const cap = Number(capacity);
    if (!Number.isInteger(cap) || cap < 1 || cap > 1000) return setNote({ kind: "error", text: "Capacity is a whole number of orders from 1 to 1000." });
    put({ vehicle, capacity: cap, start }, "Saved. If anything changed, the rider must confirm again.");
  }

  const name = rider.display_name;
  return (
    <li className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200" data-testid="round-rider" data-rider={name}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-auto font-semibold">{name} <span className="font-normal text-slate-500">({rider.username})</span></span>
        {rider.participating && <ConfirmationBadge state={rider.confirmation.state} />}
      </div>
      {rider.participating && (
        <p className="mt-1 text-sm text-slate-700" data-testid="destination-kind">Destination: {destinationLabel(rider.destination?.kind)}</p>
      )}
      {!rider.account_active && <p className="mt-1 text-sm text-red-700">Account deactivated. Remove this rider from the round.</p>}
      {rider.issues.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-amber-900" aria-label={`Open items for ${name}`}>
          {rider.issues.map((i) => <li key={i.code}>{i.reason}</li>)}
        </ul>
      )}
      {rider.participating ? (
        <form onSubmit={save} className="mt-3 grid gap-3 sm:grid-cols-[repeat(3,minmax(0,1fr))_auto] sm:items-end">
          <label className="text-sm font-medium">Vehicle
            <select className={inputClass} value={vehicle} onChange={(e) => setVehicle(e.target.value as Vehicle)} aria-label={`Vehicle for ${name}`}>
              {(Object.keys(VEHICLE_LABEL) as Vehicle[]).map((v) => <option key={v} value={v}>{VEHICLE_LABEL[v]}</option>)}
            </select>
          </label>
          <label className="text-sm font-medium">Capacity (orders)
            <input className={inputClass} type="number" min={1} max={1000} step={1} inputMode="numeric" value={capacity}
              onChange={(e) => setCapacity(e.target.value)} aria-label={`Capacity for ${name}`} required />
          </label>
          <label className="text-sm font-medium">Start
            <select className={inputClass} value={start} onChange={(e) => setStart(e.target.value as DepotKind)} aria-label={`Start for ${name}`}>
              {DEPOT_KINDS.map((k) => <option key={k} value={k}>{START_LABEL[k]}</option>)}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            <button disabled={busy} className={primaryButton} aria-label={`Save setup for ${name}`}>Save</button>
            <button type="button" disabled={busy} className={secondaryButton} onClick={() => put({ participating: false }, "Removed from this round.")}
              aria-label={`Remove ${name} from this round`}>Remove</button>
          </div>
        </form>
      ) : (
        <button type="button" disabled={busy || !rider.account_active} className={`${secondaryButton} mt-2`}
          onClick={() => put({ participating: true }, "Added back. The rider must confirm their setup.")}>Add {name} back</button>
      )}
      {note && <div className="mt-2"><Message note={note} onReload={conflict ? () => { setNote(null); onReload(); } : undefined} /></div>}
    </li>
  );
}

function AddRider({ roundId, addable, onAdded, onUnauthorized }: {
  roundId: string; addable: RiderProfile[]; onAdded: () => void; onUnauthorized: () => void;
}) {
  const [riderId, setRiderId] = useState("");
  const [vehicle, setVehicle] = useState<Vehicle | "">("");
  const [capacity, setCapacity] = useState("10");
  const [start, setStart] = useState<DepotKind>("office");
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);
  const chosen = addable.find((p) => p.id === riderId);

  async function add(e: FormEvent) {
    e.preventDefault();
    const cap = Number(capacity);
    const v = vehicle || chosen?.default_vehicle;
    if (!chosen) return setNote({ kind: "error", text: "Choose a rider to add." });
    if (!v) return setNote({ kind: "error", text: "Choose a vehicle; this rider has no default." });
    if (!Number.isInteger(cap) || cap < 1 || cap > 1000) return setNote({ kind: "error", text: "Capacity is a whole number of orders from 1 to 1000." });
    setBusy(true); setNote(null);
    try {
      await api(`/api/admin/rounds/${roundId}/riders/${chosen.id}`, { method: "PUT", json: { vehicle: v, capacity: cap, start } });
      setNote({ kind: "ok", text: `${chosen.display_name} added. They now choose and confirm a destination in their app.` });
      setRiderId(""); setVehicle("");
      onAdded();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized();
      setNote({ kind: "error", text: err instanceof ApiError ? err.message : "Could not add the rider." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Add a rider to this round" testId="add-rider">
      {addable.length === 0 ? <p className="text-slate-600">Every active rider account is already in this round. Create accounts with the CLI.</p> : (
        <form onSubmit={add} className="grid gap-3 sm:grid-cols-[repeat(4,minmax(0,1fr))_auto] sm:items-end">
          <label className="text-sm font-medium">Rider
            <select className={inputClass} value={riderId} onChange={(e) => setRiderId(e.target.value)} required>
              <option value="">Choose…</option>
              {addable.map((p) => <option key={p.id} value={p.id}>{p.display_name} ({p.username})</option>)}
            </select>
          </label>
          <label className="text-sm font-medium">Vehicle
            <select className={inputClass} value={vehicle || chosen?.default_vehicle || ""} onChange={(e) => setVehicle(e.target.value as Vehicle)}>
              {!chosen?.default_vehicle && <option value="">Choose…</option>}
              {(Object.keys(VEHICLE_LABEL) as Vehicle[]).map((v) => <option key={v} value={v}>{VEHICLE_LABEL[v]}</option>)}
            </select>
          </label>
          <label className="text-sm font-medium">Capacity (orders)
            <input className={inputClass} type="number" min={1} max={1000} step={1} inputMode="numeric" value={capacity}
              onChange={(e) => setCapacity(e.target.value)} required />
          </label>
          <label className="text-sm font-medium">Start
            <select className={inputClass} value={start} onChange={(e) => setStart(e.target.value as DepotKind)}>
              {DEPOT_KINDS.map((k) => <option key={k} value={k}>{START_LABEL[k]}</option>)}
            </select>
          </label>
          <button disabled={busy} className={primaryButton}>Add rider</button>
        </form>
      )}
      <div className="mt-3"><Message note={note} /></div>
    </Section>
  );
}
