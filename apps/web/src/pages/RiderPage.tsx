import { useEffect, useState } from "react";
import { api, ApiError, type RiderOrder } from "../api";
import { StatusPill } from "../components/Badges";

// Phase 1: read-only list of the rider's own assigned orders. Calling, navigation and status
// updates are Phase 3; assignment itself is Phase 2.
export default function RiderPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [orders, setOrders] = useState<RiderOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<RiderOrder[]>("/api/rider/orders").then(setOrders).catch((e) => {
      if (e instanceof ApiError && e.status === 401) onUnauthorized();
      else setError("Could not load your deliveries.");
    });
  }, [onUnauthorized]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">My deliveries</h1>
      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {orders === null && !error && <p role="status" className="text-slate-500">Loading…</p>}
      {orders?.length === 0 && (
        <p className="rounded-xl bg-white p-4 text-slate-600 ring-1 ring-slate-200">
          No deliveries are assigned to you yet. Your admin will assign them before the round starts.
        </p>
      )}
      <ul className="space-y-3">
        {orders?.map((o) => (
          <li key={o.id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="rider-order">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{o.order_code}</span>
              <StatusPill status={o.status} />
            </div>
            <p className="mt-2 font-semibold">{o.customer_name}</p>
            <p className="text-sm text-slate-700">{o.product}</p>
            <p className="text-sm text-slate-700">{o.contact}</p>
            {o.instructions && <p className="mt-1 text-sm text-slate-600">“{o.instructions}”</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
