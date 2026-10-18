import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { api, ApiError, type DeliveryRoundSummary, type DeliveryView as View } from "../api";
import DeliveryView from "../components/DeliveryView";
import DestinationCard from "../components/DestinationCard";
import { inputClass, secondaryButton } from "../components/ui";

// The rider's page, one round at a time (the round is in the URL, never in browser storage):
// the destination card from 2C for rounds they take part in, then (since 3A) their own
// deliveries for that round in the saved route order. Status updates are step 3B.
export default function RiderPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [params, setParams] = useSearchParams();
  const [rounds, setRounds] = useState<DeliveryRoundSummary[] | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const current = useRef<string | null>(null);
  const viewAc = useRef<AbortController | null>(null);

  const fail = useCallback((message: string) => (e: unknown) => {
    if (e instanceof DOMException && e.name === "AbortError") return;
    if (e instanceof ApiError && e.status === 401) return onUnauthorized();
    setError(e instanceof ApiError && e.status === 404 ? "This round is not available to you." : message);
  }, [onUnauthorized]);

  const loadRounds = useCallback((signal?: AbortSignal) =>
    api<DeliveryRoundSummary[]>("/api/rider/delivery-rounds", { signal }).then((r) => { if (!signal?.aborted) setRounds(r); }), []);

  useEffect(() => {
    const ac = new AbortController();
    loadRounds(ac.signal).catch(fail("Could not load your rounds."));
    return () => ac.abort();
  }, [loadRounds, fail]);

  const requested = params.get("round");
  const roundId = rounds ? (rounds.find((r) => r.round_id === requested)?.round_id ?? rounds[0]?.round_id ?? null) : null;
  current.current = roundId;
  const selected = rounds?.find((r) => r.round_id === roundId) ?? null;

  /** Load the delivery view for one round; a newer load or a round switch aborts it, and a
   * response for a round that is no longer selected is dropped. */
  const loadView = useCallback((id: string) => {
    viewAc.current?.abort();
    const ac = new AbortController();
    viewAc.current = ac;
    setLoading(true);
    api<View>(`/api/rider/rounds/${id}/deliveries`, { signal: ac.signal })
      .then((v) => { if (!ac.signal.aborted && current.current === id) { setView(v); setError(null); } })
      .catch(fail("Could not load your deliveries."))
      .finally(() => { if (viewAc.current === ac) { viewAc.current = null; setLoading(false); } });
  }, [fail]);

  useEffect(() => {
    if (!roundId) return;
    setView(null); setError(null);
    loadView(roundId);
    return () => { viewAc.current?.abort(); viewAc.current = null; };
  }, [roundId, loadView]);

  const refresh = useCallback(() => {
    if (!roundId) return;
    loadView(roundId);
    loadRounds().catch(fail("Could not load your rounds."));
  }, [roundId, loadView, loadRounds, fail]);

  const select = (id: string) => setParams((p) => { const next = new URLSearchParams(p); next.set("round", id); return next; });
  const needConfirm = rounds?.filter((r) => r.participating && r.confirmation !== "confirmed" && r.round_id !== roundId) ?? [];

  if (rounds === null) {
    return error ? <p role="alert" className="text-red-800">{error}</p> : <p role="status" className="text-slate-500">Loading…</p>;
  }
  if (rounds.length === 0) {
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-semibold">My deliveries</h1>
        <p className="rounded-xl bg-white p-4 text-slate-600 ring-1 ring-slate-200" data-testid="no-rounds">
          You are not part of any round yet. Your admin adds you to a round, then you choose and confirm where your route ends.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">My deliveries</h1>
        <label className="block w-full min-w-0 text-sm font-medium sm:w-auto">Round
          <select className={`${inputClass} sm:max-w-md`} value={roundId ?? ""} onChange={(e) => select(e.target.value)}>
            {rounds.map((r) => (
              <option key={r.round_id} value={r.round_id}>
                {r.round_name} — {r.participating && r.confirmation !== "confirmed" ? "confirm your setup" : `${r.orders.pending} to deliver`}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={secondaryButton} onClick={refresh} disabled={loading}>Refresh</button>
      </div>
      {needConfirm.length > 0 && (
        <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-950 ring-1 ring-amber-200" data-testid="other-rounds-to-confirm">
          <p>Other rounds need your confirmation:</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {needConfirm.map((r) => (
              <li key={r.round_id}>
                <button type="button" className="min-h-11 rounded-md bg-white px-3 font-medium underline ring-1 ring-amber-300" onClick={() => select(r.round_id)}>
                  {r.round_name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {selected?.participating && (
        <section className="space-y-2" aria-labelledby="my-setup">
          <h2 id="my-setup" className="text-lg font-semibold">My setup for this round</h2>
          <ul>
            <DestinationCard key={selected.round_id} roundId={selected.round_id} roundName={selected.round_name}
              onUnauthorized={onUnauthorized} onChanged={refresh} />
          </ul>
        </section>
      )}
      <section className="space-y-2" aria-labelledby="my-round-deliveries">
        <h2 id="my-round-deliveries" className="sr-only">Deliveries for {selected?.round_name}</h2>
        {view && view.round_id === roundId ? <DeliveryView view={view} /> : !error && <p role="status" className="text-slate-500">Loading deliveries…</p>}
      </section>
    </div>
  );
}
