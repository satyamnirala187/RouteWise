import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api, ApiError, isDefiniteRefusal, type AdminOrder, type Readiness, type RoundRider, type StopGroupOrderRef, type StopGroupOverview } from "../api";
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
      {order.stop_group && (
        <span className="rounded-full bg-teal-100 px-2 py-0.5 text-xs font-semibold text-teal-900" data-testid="group-badge">
          🏢 One stop with {order.stop_group.members.filter((c) => c !== order.order_code).join(", ")}
        </span>
      )}
      {!order.stop_group && order.same_pin_as.length > 0 && (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-950" data-testid="same-pin-badge">
          Same pin as {order.same_pin_as.join(", ")}
        </span>
      )}
    </>
  );
}

/** What a refresh did to the data on screen (see `refresh`). */
type Refreshed = "applied" | "failed" | "obsolete";

export default function OrdersPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const handle = useErrorHandler(onUnauthorized, setError, "Could not load orders.");
  const { rounds, roundId, select } = useRounds(handle);
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [riders, setRiders] = useState<RoundRider[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [groups, setGroups] = useState<StopGroupOverview | null>(null);
  const [onlyNeedsPin, setOnlyNeedsPin] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const wide = useIsWide();
  const selected = useRef<string | null>(null);  // the round on screen right now
  selected.current = roundId;
  const newest = useRef(0);                       // the most recent refresh request; older answers are dropped

  /** Reload orders, readiness, riders and the group overview of the round on screen. Answers apply only if this
   * is still the newest request for the selected round, so a slow answer for an earlier request or another round
   * can never replace what is shown. A request for a round that is no longer selected is not even sent.
   * The result says what happened to the data on screen: "applied" (this round's data was loaded), "failed" (the
   * load failed) or "obsolete" (another round was selected). A request overtaken by a newer one for the same
   * round reports what that newer request produced. */
  const latest = useRef<Promise<Refreshed>>(Promise.resolve("obsolete"));
  const refresh = useCallback((id: string, signal?: AbortSignal): Promise<Refreshed> => {
    if (id !== selected.current) return Promise.resolve("obsolete");
    const mine = ++newest.current;
    const onScreen = () => !signal?.aborted && id === selected.current;
    const request: Promise<Refreshed> = Promise.all([
      api<AdminOrder[]>(`/api/admin/rounds/${id}/orders`, { signal }),
      api<Readiness>(`/api/admin/rounds/${id}/readiness`, { signal }),
      api<RoundRider[]>(`/api/admin/rounds/${id}/riders`, { signal }),
      api<StopGroupOverview>(`/api/admin/rounds/${id}/stop-groups`, { signal }),
    ]).then(([o, r, rr, g]): Refreshed | Promise<Refreshed> => {
      if (!onScreen()) return "obsolete";           // another round was selected meanwhile
      if (mine !== newest.current) return latest.current;  // a newer request for this round decides
      setOrders(o); setReadiness(r); setRiders(rr); setGroups(g); setError(null);
      return "applied";
    }).catch((e): Refreshed | Promise<Refreshed> => {
      if (!onScreen()) return "obsolete";
      if (mine !== newest.current) return latest.current;
      handle(e);
      return "failed";
    });
    latest.current = request;
    return request;
  }, [handle]);

  useEffect(() => {
    if (!roundId) return;
    setOrders([]); setReadiness(null); setRiders([]); setGroups(null); setEditing(null);
    const ac = new AbortController();
    refresh(roundId, ac.signal);
    return () => ac.abort();
  }, [roundId, refresh]);

  function saved(updated: AdminOrder) {
    setOrders((list) => list.map((o) => (o.id === updated.id ? updated : o)));  // shown at once; the reload below confirms
    // Any saved edit can change which orders are suggested together (a pin), free another order (a group
    // notice), or move versions the group panel holds: reload orders, readiness and the group overview.
    if (roundId) refresh(roundId);
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

      {roundId && groups && (
        <StopGroups key={`stop-groups-${roundId}`} roundId={roundId} overview={groups} onDone={() => refresh(roundId)} onUnauthorized={onUnauthorized} />
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

/** Same-building stops (step 4C). Orders with EXACTLY the same pin are suggested; nothing is grouped until
 * the admin confirms. Nearby pins are never suggested, and identical pins may stay separate stops (different
 * entrances). Grouping changes no status, customer detail or owner. */
const UNCERTAIN_CHANGE = "Could not confirm the change. Reload to check the current groups.";

function StopGroups({ roundId, overview, onDone, onUnauthorized }: {
  roundId: string; overview: StopGroupOverview; onDone: () => Promise<Refreshed>; onUnauthorized: () => void;
}) {
  const [note, setNote] = useState<Note>(null);
  const [reload, setReload] = useState<"conflict" | "uncertain" | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloading, setReloading] = useState(false);
  const alive = useRef(true);  // this panel belongs to one round; once another is selected it is gone
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  /** Send one change. "Nothing was changed" is said only when the API itself rejected the request. A network
   * failure, an unreadable answer or a server error leaves the outcome unknown (the server may have committed
   * the change), so it is reported as such, with a reload of the current server data. A mutation is never retried here. */
  async function run(action: () => Promise<string>) {
    setBusy(true); setNote(null); setReload(null);
    try {
      setNote({ kind: "ok", text: await action() });
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return onUnauthorized();
      if (isDefiniteRefusal(e)) {
        const refusal = e as ApiError;
        setReload(refusal.status === 409 ? "conflict" : null);
        setNote({ kind: "error", text: `${refusal.message} Nothing was changed.`, details: refusal.details });
      } else {
        setReload("uncertain");
        setNote({ kind: "warn", text: UNCERTAIN_CHANGE });
      }
    } finally {
      setBusy(false);
    }
  }

  /** Fetch the current server data (a read, never a repeat of the change). While it loads, a loading state shows.
   * Only a successful load of this round confirms the reload: after an uncertain outcome the loaded lists are
   * the answer, and the message says so. If the load fails the earlier warning and the reload button stay, so
   * it can be read again; the change itself is never sent again. */
  async function reloadFromServer() {
    setReloading(true);
    const outcome = await onDone();
    if (!alive.current) return;  // another round was selected meanwhile: nothing here applies any more
    setReloading(false);
    if (outcome !== "applied") return;
    setNote(reload === "uncertain" ? { kind: "ok", text: "Reloaded: these are the groups the server has now." } : null);
    setReload(null);
  }

  /** The whole stop: the suggested orders plus every member of any group they already belong to. */
  function groupAsOneStop(suggested: (StopGroupOrderRef & { stop_group: string | null })[]) {
    const all = new Map<string, StopGroupOrderRef>();
    for (const o of suggested) {
      all.set(o.id, o);
      for (const m of overview.groups.find((g) => g.id === o.stop_group)?.orders ?? []) all.set(m.id, m);
    }
    return run(async () => {
      const r = await api<{ group: { orders: string[] } }>(`/api/admin/rounds/${roundId}/stop-groups`, {
        method: "POST", json: { orders: [...all.values()].map((o) => ({ id: o.id, version: o.version })) },
      });
      return `${r.group.orders.join(", ")} now share one stop. Statuses, customers and riders are unchanged; re-optimize to plan with it.`;
    });
  }

  const ungroup = (o: StopGroupOrderRef) => run(async () => {
    const r = await api<{ notice: string }>(`/api/admin/orders/${o.id}/stop-group`, { method: "DELETE", json: { version: o.version } });
    return `${r.notice} Re-optimize to plan without it.`;
  });

  const count = overview.suggestions.length + overview.groups.length;
  return (
    <details className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="stop-groups">
      <summary className="min-h-11 cursor-pointer content-center font-semibold">
        Same-building stops{count > 0 ? ` (${overview.groups.length} grouped, ${overview.suggestions.length} suggested)` : ""}
      </summary>
      <p className="mt-2 text-sm text-slate-600">
        Orders with exactly the same pin can be one stop for the rider. Nothing is grouped until you confirm it. Nearby pins are never
        suggested or grouped, and identical pins can stay separate stops if they are different entrances. Grouping changes no status,
        customer detail or owner; changing a grouped order's pin takes it out of its group.
      </p>
      {count === 0 && <p className="mt-2 text-sm text-slate-600" data-testid="no-stop-groups">No orders share an identical pin.</p>}

      {overview.suggestions.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label="Suggested stops">
          {overview.suggestions.map((s) => (
            <li key={s.orders.map((o) => o.id).join()} className="rounded-lg bg-amber-50 p-3 text-sm ring-1 ring-amber-200" data-testid="group-suggestion">
              <p className="font-medium">Same pin: {s.orders.map((o) => `${o.order_code} (${o.status})`).join(", ")}</p>
              <button type="button" disabled={busy || reloading} className={`${primaryButton} mt-2`} onClick={() => groupAsOneStop(s.orders)}>
                Group as one stop
              </button>
            </li>
          ))}
        </ul>
      )}

      {overview.groups.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label="Stop groups">
          {overview.groups.map((g) => (
            <li key={g.id} className="rounded-lg bg-teal-50 p-3 text-sm ring-1 ring-teal-200" data-testid="stop-group">
              <p className="font-medium">One stop: {g.orders.map((o) => o.order_code).join(", ")}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {g.orders.map((o) => (
                  <button key={o.id} type="button" disabled={busy || reloading} className={secondaryButton} onClick={() => ungroup(o)}
                    aria-label={`Ungroup ${o.order_code}`}>
                    Ungroup {o.order_code}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xs text-slate-600">A group left with one order is dissolved.</p>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3">
        {reloading
          ? <p role="status" data-testid="groups-reloading" className="rounded-md bg-slate-100 px-3 py-2 text-sm text-slate-800">Reloading the current groups…</p>
          : <Message note={note} reloadLabel={reload === "uncertain" ? "Reload the current groups" : undefined}
              onReload={reload ? () => reloadFromServer() : undefined} />}
      </div>
    </details>
  );
}
