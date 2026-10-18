import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { api, ApiError, type AdminOrder, type Readiness, type RoundRider } from "../api";
import { LocationBadge, StatusPill } from "../components/Badges";
import OrderEditor from "../components/OrderEditor";
import { inputClass, Message, primaryButton, RoundPicker, secondaryButton, type Note } from "../components/ui";
import { useIsWide } from "../useIsWide";
import { useErrorHandler, useRounds } from "../useRounds";

/** Owner (assigned rider from the current plan) and owner lock are different things and are
 * always shown separately. */
function PlanningBadges({ order, names }: { order: AdminOrder; names: Record<string, string> }) {
  const p = order.planning;
  return (
    <>
      {p.assigned_rider_id && (
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-800" data-testid="assigned-badge">
          Assigned: {names[p.assigned_rider_id] ?? "rider not in round"}
        </span>
      )}
      {p.locked_rider_id && (
        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-900" data-testid="lock-badge">
          🔒 Locked to {names[p.locked_rider_id] ?? "rider not in round"}
        </span>
      )}
      {p.first_priority && (
        <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-900" data-testid="priority-badge">First delivery</span>
      )}
    </>
  );
}

export default function OrdersPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const handle = useErrorHandler(onUnauthorized, setError, "Could not load orders.");
  const { rounds, roundId, select } = useRounds(handle);
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [riders, setRiders] = useState<RoundRider[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [onlyNeedsPin, setOnlyNeedsPin] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const wide = useIsWide();

  const refresh = useCallback((id: string, signal?: AbortSignal) => {
    Promise.all([
      api<AdminOrder[]>(`/api/admin/rounds/${id}/orders`, { signal }),
      api<Readiness>(`/api/admin/rounds/${id}/readiness`, { signal }),
      api<RoundRider[]>(`/api/admin/rounds/${id}/riders`, { signal }),
    ]).then(([o, r, rr]) => {
      if (signal?.aborted) return;  // another round was selected meanwhile
      setOrders(o); setReadiness(r); setRiders(rr);
    }).catch(handle);
  }, [handle]);

  useEffect(() => {
    if (!roundId) return;
    setOrders([]); setReadiness(null); setRiders([]); setEditing(null);
    const ac = new AbortController();
    refresh(roundId, ac.signal);
    return () => ac.abort();
  }, [roundId, refresh]);

  function saved(updated: AdminOrder) {
    setOrders((list) => list.map((o) => (o.id === updated.id ? updated : o)));
    if (roundId) api<Readiness>(`/api/admin/rounds/${roundId}/readiness`).then(setReadiness).catch(handle);
  }

  if (rounds === null) return error ? <p role="alert" className="text-red-800">{error}</p> : <p role="status" className="text-slate-500">Loading…</p>;
  if (rounds.length === 0) {
    return (
      <div className="rounded-xl bg-white p-6 ring-1 ring-slate-200">
        <h1 className="text-xl font-semibold">Orders</h1>
        <p className="mt-2 text-slate-600">No orders yet. <Link className="font-medium text-brand-700 underline" to="/admin/import">Import an Excel file</Link> to start.</p>
      </div>
    );
  }

  const names = Object.fromEntries(riders.map((r) => [r.rider_id, r.display_name]));
  const participating = riders.filter((r) => r.participating);
  const shown = onlyNeedsPin ? orders.filter((o) => o.location.state !== "resolved" || o.location.in_service_area === false) : orders;
  const editor = (o: AdminOrder) => (
    <OrderEditor order={o} riders={participating} onSaved={saved} onClose={() => setEditing(null)} onUnauthorized={onUnauthorized} />
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">Orders</h1>
        <RoundPicker rounds={rounds} roundId={roundId} onSelect={select} />
        <label className="flex min-h-11 items-center gap-2 text-sm font-medium">
          <input type="checkbox" className="size-5" checked={onlyNeedsPin} onChange={(e) => setOnlyNeedsPin(e.target.checked)} />
          Only orders needing a pin
        </label>
      </div>

      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}

      {readiness && (
        <div data-testid="readiness" role="status"
          className={`rounded-lg px-4 py-3 text-sm ring-1 ${readiness.ready ? "bg-emerald-50 text-emerald-900 ring-emerald-200" : "bg-amber-50 text-amber-950 ring-amber-200"}`}>
          {readiness.orders_ready
            ? `All ${readiness.orders} orders have a valid pin.`
            : `${readiness.blockers.length} of ${readiness.orders} orders need a valid pin. Planning is blocked until they are fixed.`}
          {readiness.configuration_blockers.length > 0 &&
            ` Rider setup: ${readiness.configuration_blockers.length} item(s) to finish before planning.`}
          {" "}<Link className="font-medium underline" to={`/admin/plan?round=${roundId}`}>Open planning</Link>
        </div>
      )}

      {roundId && participating.length > 0 && (
        <BulkAssign key={roundId} roundId={roundId} orders={orders} riders={participating} names={names}
          onDone={() => refresh(roundId)} onUnauthorized={onUnauthorized} />
      )}

      {/* Phones: cards */}
      {!wide && <ul className="space-y-3" aria-label="Orders">
        {shown.map((o) => (
          <li key={o.id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="order-card">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{o.order_code}</span>
              <StatusPill status={o.status} />
              <LocationBadge location={o.location} />
              <PlanningBadges order={o} names={names} />
            </div>
            <p className="mt-2 font-semibold">{o.customer_name}</p>
            <p className="text-sm text-slate-700">{o.product}</p>
            <p className="text-sm text-slate-700">{o.contact}</p>
            {o.instructions && <p className="mt-1 text-sm text-slate-600">“{o.instructions}”</p>}
            {o.location.state !== "resolved" && <p className="mt-1 text-sm text-red-700">{o.location.note}</p>}
            <div className="mt-3">
              {editing === o.id ? editor(o) : (
                <button type="button" onClick={() => setEditing(o.id)}
                  className="min-h-11 w-full rounded-md px-4 font-semibold ring-1 ring-slate-300">Edit</button>
              )}
            </div>
          </li>
        ))}
      </ul>}

      {/* Tablets and desktops: table */}
      {wide && <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">Order</th><th className="px-3 py-2">Customer</th><th className="px-3 py-2">Product</th>
              <th className="px-3 py-2">Contact</th><th className="px-3 py-2">Location</th><th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Rider</th>
              <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((o) => (
              <Fragment key={o.id}>
                <tr className="border-t border-slate-100 align-top" data-testid="order-row">
                  <td className="px-3 py-2 font-mono text-xs text-slate-500">{o.order_code}<br />row {o.source_row}</td>
                  <td className="px-3 py-2 font-medium">{o.customer_name}{o.instructions && <p className="font-normal text-slate-500">“{o.instructions}”</p>}</td>
                  <td className="px-3 py-2">{o.product}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{o.contact}</td>
                  <td className="px-3 py-2"><LocationBadge location={o.location} />
                    {o.location.state !== "resolved" && <p className="mt-1 max-w-56 text-xs text-red-700">{o.location.note}</p>}</td>
                  <td className="px-3 py-2"><StatusPill status={o.status} /></td>
                  <td className="px-3 py-2"><div className="flex flex-col items-start gap-1"><PlanningBadges order={o} names={names} /></div></td>
                  <td className="px-3 py-2 text-right">
                    <button type="button" onClick={() => setEditing(editing === o.id ? null : o.id)}
                      className="min-h-9 rounded-md px-3 font-semibold ring-1 ring-slate-300">{editing === o.id ? "Close" : "Edit"}</button>
                  </td>
                </tr>
                {editing === o.id && (
                  <tr><td colSpan={8} className="px-3 pb-3">{editor(o)}</td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>}
      {shown.length === 0 && orders.length > 0 && <p className="text-slate-600">No orders match this filter.</p>}
    </div>
  );
}

/** Manual assignment for many orders at once (all succeed or none do, with version checks). */
function BulkAssign({ roundId, orders, riders, names, onDone, onUnauthorized }: {
  roundId: string; orders: AdminOrder[]; riders: RoundRider[]; names: Record<string, string>; onDone: () => void; onUnauthorized: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [riderId, setRiderId] = useState("");
  const [note, setNote] = useState<Note>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = orders.filter((o) => o.status === "Pending");
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  async function apply() {
    const chosen = orders.filter((o) => selected.has(o.id));
    if (chosen.length === 0) return setNote({ kind: "error", text: "Select at least one order." });
    setBusy(true); setNote(null); setConflict(false);
    try {
      const r = await api<{ changed: number }>(`/api/admin/rounds/${roundId}/locks`, {
        method: "POST", json: { rider_id: riderId || null, orders: chosen.map((o) => ({ id: o.id, version: o.version })) },
      });
      setNote({ kind: "ok", text: riderId ? `${r.changed} order(s) locked to ${names[riderId]}.` : `${r.changed} lock(s) cleared.` });
      setSelected(new Set());
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return onUnauthorized();
      setConflict(e instanceof ApiError && e.status === 409);
      setNote({ kind: "error", text: e instanceof ApiError ? `${e.message} Nothing was changed.` : "Assignment failed.", details: e instanceof ApiError ? e.details : [] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="bulk-assign">
      <summary className="min-h-11 cursor-pointer content-center font-semibold">Bulk owner assignment (for manual mode)</summary>
      <p className="mt-2 text-sm text-slate-600">Select Pending orders and lock them to one rider in a single step. If any order changed meanwhile, nothing is saved.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={secondaryButton} onClick={() => setSelected(new Set(pending.filter((o) => !o.planning.locked_rider_id).map((o) => o.id)))}>
          Select unlocked Pending
        </button>
        <button type="button" className={secondaryButton} onClick={() => setSelected(new Set())}>Clear selection</button>
      </div>
      <ul className="mt-3 grid max-h-72 gap-1 overflow-y-auto sm:grid-cols-2" aria-label="Orders to assign">
        {pending.map((o) => (
          <li key={o.id}>
            <label className="flex min-h-11 items-center gap-2 rounded-md px-2 text-sm hover:bg-slate-50">
              <input type="checkbox" className="size-5" checked={selected.has(o.id)} onChange={() => toggle(o.id)} />
              <span className="font-mono text-xs text-slate-500">{o.order_code}</span>
              <span className="min-w-0 truncate">{o.customer_name}</span>
              {o.planning.locked_rider_id && <span className="text-xs text-indigo-800">🔒 {names[o.planning.locked_rider_id]}</span>}
            </label>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1 text-sm font-medium">Lock selected orders to
          <select className={inputClass} value={riderId} onChange={(e) => setRiderId(e.target.value)}>
            <option value="">No one (clear their locks)</option>
            {riders.map((r) => <option key={r.rider_id} value={r.rider_id}>{r.display_name}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy} className={primaryButton} onClick={apply}>Apply to {selected.size} order(s)</button>
      </div>
      <div className="mt-3"><Message note={note} onReload={conflict ? () => { setNote(null); onDone(); } : undefined} /></div>
    </details>
  );
}
