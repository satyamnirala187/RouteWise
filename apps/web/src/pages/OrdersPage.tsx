import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { api, ApiError, type AdminOrder, type Readiness, type RoundSummary } from "../api";
import { LocationBadge, StatusPill } from "../components/Badges";
import OrderEditor from "../components/OrderEditor";
import { useIsWide } from "../useIsWide";

export default function OrdersPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [rounds, setRounds] = useState<RoundSummary[] | null>(null);
  const [roundId, setRoundId] = useState<string | null>(null);
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [onlyNeedsPin, setOnlyNeedsPin] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wide = useIsWide();

  const handle = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) onUnauthorized();
    else setError(e instanceof ApiError ? e.message : "Could not load orders.");
  }, [onUnauthorized]);

  useEffect(() => {
    api<RoundSummary[]>("/api/admin/rounds").then((r) => {
      setRounds(r);
      setRoundId((cur) => cur ?? r[0]?.id ?? null);
    }).catch(handle);
  }, [handle]);

  const refresh = useCallback((id: string) => {
    Promise.all([
      api<AdminOrder[]>(`/api/admin/rounds/${id}/orders`),
      api<Readiness>(`/api/admin/rounds/${id}/readiness`),
    ]).then(([o, r]) => { setOrders(o); setReadiness(r); }).catch(handle);
  }, [handle]);

  useEffect(() => { if (roundId) refresh(roundId); }, [roundId, refresh]);

  function saved(updated: AdminOrder) {
    setOrders((list) => list.map((o) => (o.id === updated.id ? updated : o)));
    if (roundId) api<Readiness>(`/api/admin/rounds/${roundId}/readiness`).then(setReadiness).catch(handle);
  }

  if (rounds === null) return <p role="status" className="text-slate-500">Loading…</p>;
  if (rounds.length === 0) {
    return (
      <div className="rounded-xl bg-white p-6 ring-1 ring-slate-200">
        <h1 className="text-xl font-semibold">Orders</h1>
        <p className="mt-2 text-slate-600">No orders yet. <Link className="font-medium text-brand-700 underline" to="/admin/import">Import an Excel file</Link> to start.</p>
      </div>
    );
  }

  const shown = onlyNeedsPin ? orders.filter((o) => o.location.state !== "resolved" || o.location.in_service_area === false) : orders;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">Orders</h1>
        <label className="text-sm font-medium">Import
          <select className="ml-2 min-h-11 rounded-md border border-slate-300 bg-white px-2" value={roundId ?? ""}
            onChange={(e) => { setRoundId(e.target.value); setEditing(null); }}>
            {rounds.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.orders})</option>)}
          </select>
        </label>
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
        </div>
      )}

      {/* Phones: cards */}
      {!wide && <ul className="space-y-3" aria-label="Orders">
        {shown.map((o) => (
          <li key={o.id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="order-card">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{o.order_code}</span>
              <StatusPill status={o.status} />
              <LocationBadge location={o.location} />
            </div>
            <p className="mt-2 font-semibold">{o.customer_name}</p>
            <p className="text-sm text-slate-700">{o.product}</p>
            <p className="text-sm text-slate-700">{o.contact}</p>
            {o.instructions && <p className="mt-1 text-sm text-slate-600">“{o.instructions}”</p>}
            {o.location.state !== "resolved" && <p className="mt-1 text-sm text-red-700">{o.location.note}</p>}
            <div className="mt-3">
              {editing === o.id ? (
                <OrderEditor order={o} onSaved={saved} onClose={() => setEditing(null)} onUnauthorized={onUnauthorized} />
              ) : (
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
                  <td className="px-3 py-2 text-right">
                    <button type="button" onClick={() => setEditing(editing === o.id ? null : o.id)}
                      className="min-h-9 rounded-md px-3 font-semibold ring-1 ring-slate-300">{editing === o.id ? "Close" : "Edit"}</button>
                  </td>
                </tr>
                {editing === o.id && (
                  <tr><td colSpan={7} className="px-3 pb-3">
                    <OrderEditor order={o} onSaved={saved} onClose={() => setEditing(null)} onUnauthorized={onUnauthorized} />
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>}
      {shown.length === 0 && <p className="text-slate-600">No orders match this filter.</p>}
    </div>
  );
}
