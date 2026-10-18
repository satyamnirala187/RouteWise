import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, DEPOT_KINDS, VEHICLE_LABEL, type Depot, type DepotKind, type Depots, type RiderProfile, type Vehicle } from "../api";
import { mapsUrl } from "../components/Badges";
import { COORD_HELP, inputClass, Message, parseCoords, primaryButton, Section, type Note } from "../components/ui";
import { useErrorHandler } from "../useRounds";

const DEPOT_NAME: Record<DepotKind, string> = { office: "Office", warehouse: "Warehouse" };

// Office/Warehouse and rider profiles (2C). Accounts are created and deactivated with the CLI.
export default function SettingsPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [depots, setDepots] = useState<Depots | null>(null);
  const [riders, setRiders] = useState<RiderProfile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const handle = useErrorHandler(onUnauthorized, setError, "Could not load settings.");

  const load = useCallback((signal?: AbortSignal) => {
    api<Depots>("/api/admin/depots", { signal }).then(setDepots).catch(handle);
    api<RiderProfile[]>("/api/admin/riders", { signal }).then(setRiders).catch(handle);
  }, [handle]);
  useEffect(() => { const ac = new AbortController(); load(ac.signal); return () => ac.abort(); }, [load]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Office, Warehouse and riders</h1>
      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {depots === null || riders === null ? <p role="status" className="text-slate-500">Loading…</p> : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {DEPOT_KINDS.map((k) => (
              <DepotCard key={k} kind={k} depot={depots[k]} onUnauthorized={onUnauthorized}
                onSaved={(d) => setDepots((cur) => cur && { ...cur, [k]: d })} onReload={() => load()} />
            ))}
          </div>
          <Section title="Rider profiles" testId="rider-profiles">
            <p className="mb-3 text-sm text-slate-600">
              Rider accounts are created and deactivated with the command-line tool (see DEVELOPMENT.md). Here you can
              change a rider's display name and default vehicle; per-round setup is on <b>Round setup</b>.
            </p>
            {riders.length === 0 ? <p className="text-slate-600">No rider accounts yet.</p> : (
              <ul className="divide-y divide-slate-100">
                {riders.map((r) => (
                  <RiderProfileRow key={r.id} rider={r} onUnauthorized={onUnauthorized} onReload={() => load()}
                    onSaved={(u) => setRiders((list) => list && list.map((x) => (x.id === u.id ? u : x)))} />
                ))}
              </ul>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

function DepotCard({ kind, depot, onSaved, onReload, onUnauthorized }: {
  kind: DepotKind; depot: Depot | null; onSaved: (d: Depot) => void; onReload: () => void; onUnauthorized: () => void;
}) {
  const [label, setLabel] = useState(depot?.label ?? DEPOT_NAME[kind]);
  const [coords, setCoords] = useState(depot ? `${depot.lat}, ${depot.lng}` : "");
  const [note, setNote] = useState<Note>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  // A newer server version (after a save or a reload) replaces the form fields.
  useEffect(() => {
    setLabel(depot?.label ?? DEPOT_NAME[kind]);
    setCoords(depot ? `${depot.lat}, ${depot.lng}` : "");
  }, [depot?.version]); // only a new server version resets the form
  const reload = () => { setNote(null); setConflict(false); onReload(); };

  async function save(e: FormEvent) {
    e.preventDefault();
    const c = parseCoords(coords);
    if (!c) return setNote({ kind: "error", text: `Enter the ${DEPOT_NAME[kind]} as latitude, longitude (for example 28.6951, 77.2147).` });
    setBusy(true); setNote(null); setConflict(false);
    try {
      const saved = await api<Depot>(`/api/admin/depots/${kind}`, {
        method: "PUT", json: { version: depot?.version ?? null, label: label.trim(), lat: c[0], lng: c[1] },
      });
      const n = saved.confirmations_invalidated ?? 0;
      onSaved(saved);
      setNote(n > 0
        ? { kind: "warn", text: `Saved. ${n} rider confirmation(s) used the old location and must be confirmed again.` }
        : { kind: "ok", text: "Saved." });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized();
      setConflict(err instanceof ApiError && err.status === 409);
      setNote({ kind: "error", text: err instanceof ApiError ? err.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  }

  const id = `depot-${kind}`;
  return (
    <Section title={DEPOT_NAME[kind]} testId={id}>
      {!depot && <p className="mb-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-950">Not set yet. Riders cannot start or end here until it is.</p>}
      <form onSubmit={save} className="space-y-3">
        <label className="block text-sm font-medium">Label
          <input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} required maxLength={100} />
        </label>
        <label className="block text-sm font-medium">Coordinates (latitude, longitude)
          <input className={inputClass} value={coords} onChange={(e) => setCoords(e.target.value)} placeholder="28.6951, 77.2147"
            inputMode="decimal" aria-describedby={`${id}-help`} required />
        </label>
        <p id={`${id}-help`} className="text-xs text-slate-600">{COORD_HELP} Moving it asks every rider who starts or ends here to confirm again.</p>
        <div className="flex flex-wrap items-center gap-3">
          <button disabled={busy} className={primaryButton}>{depot ? `Save ${DEPOT_NAME[kind]}` : `Set ${DEPOT_NAME[kind]}`}</button>
          {depot && (
            <a className="text-sm font-medium text-brand-700 underline" target="_blank" rel="noopener noreferrer" href={mapsUrl(depot.lat, depot.lng)}>
              Check in Google Maps ↗
            </a>
          )}
        </div>
      </form>
      <div className="mt-3"><Message note={note} onReload={conflict ? reload : undefined} /></div>
    </Section>
  );
}

function RiderProfileRow({ rider, onSaved, onReload, onUnauthorized }: {
  rider: RiderProfile; onSaved: (r: RiderProfile) => void; onReload: () => void; onUnauthorized: () => void;
}) {
  const [name, setName] = useState(rider.display_name);
  const [vehicle, setVehicle] = useState<Vehicle | "">(rider.default_vehicle ?? "");
  const [note, setNote] = useState<Note>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setName(rider.display_name); setVehicle(rider.default_vehicle ?? ""); }, [rider.version]);
  const reload = () => { setNote(null); setConflict(false); onReload(); };

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setNote(null); setConflict(false);
    try {
      const saved = await api<RiderProfile>(`/api/admin/riders/${rider.id}`, {
        method: "PATCH", json: { version: rider.version, display_name: name.trim(), ...(vehicle ? { default_vehicle: vehicle } : {}) },
      });
      onSaved(saved);
      setNote({ kind: "ok", text: "Saved." });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized();
      setConflict(err instanceof ApiError && err.status === 409);
      setNote({ kind: "error", text: err instanceof ApiError ? err.message : "Save failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="py-3" data-testid="rider-profile">
      <form onSubmit={save} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <label className="text-sm font-medium">Display name <span className="font-normal text-slate-500">({rider.username})</span>
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} />
        </label>
        <label className="text-sm font-medium">Default vehicle
          <select className={inputClass} value={vehicle} onChange={(e) => setVehicle(e.target.value as Vehicle)}>
            {!rider.default_vehicle && <option value="">Not set</option>}
            {(Object.keys(VEHICLE_LABEL) as Vehicle[]).map((v) => <option key={v} value={v}>{VEHICLE_LABEL[v]}</option>)}
          </select>
        </label>
        <button disabled={busy} className={primaryButton} aria-label={`Save profile for ${rider.display_name}`}>Save</button>
      </form>
      {!rider.account_active && <p className="mt-1 text-sm text-red-700">Account deactivated (CLI). This rider cannot join rounds.</p>}
      {note && <div className="mt-2"><Message note={note} onReload={conflict ? reload : undefined} /></div>}
    </li>
  );
}
