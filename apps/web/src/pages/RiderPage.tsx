import { useEffect, useState } from "react";
import { api, ApiError, type RiderOrder, type RiderRoundSummary } from "../api";
import { StatusPill } from "../components/Badges";
import DestinationCard from "../components/DestinationCard";

// The rider's own deliveries (Phase 1, read-only) and, since 2C, a destination card for each
// round they take part in. Calling, navigation and status updates are Phase 3.
export default function RiderPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [orders, setOrders] = useState<RiderOrder[] | null>(null);
  const [rounds, setRounds] = useState<RiderRoundSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    const fail = (message: string) => (e: unknown) => {
      if (ac.signal.aborted) return;
      if (e instanceof ApiError && e.status === 401) onUnauthorized();
      else setError(message);
    };
    api<RiderOrder[]>("/api/rider/orders", { signal: ac.signal }).then(setOrders).catch(fail("Could not load your deliveries."));
    api<RiderRoundSummary[]>("/api/rider/rounds", { signal: ac.signal }).then(setRounds).catch(fail("Could not load your rounds."));
    return () => ac.abort();
  }, [onUnauthorized]);

  return (
    <div className="space-y-6">
      <h1 className="sr-only">My rounds and deliveries</h1>
      {rounds && rounds.length > 0 && (
        <section className="space-y-3" aria-labelledby="my-rounds">
          <h2 id="my-rounds" className="text-xl font-semibold">My rounds</h2>
          <p className="text-sm text-slate-600">Choose where each route ends, save it, then confirm your setup. Your admin cannot plan the round until you confirm.</p>
          <ul className="space-y-3">
            {rounds.map((r) => <DestinationCard key={r.round_id} roundId={r.round_id} roundName={r.round_name} onUnauthorized={onUnauthorized} />)}
          </ul>
        </section>
      )}
      <section className="space-y-4" aria-labelledby="my-deliveries">
        <h2 id="my-deliveries" className="text-xl font-semibold">My deliveries</h2>
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
      </section>
    </div>
  );
}
