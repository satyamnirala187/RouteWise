import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { api, ApiError, type DeliveryItem, type DeliveryRoundSummary, type DeliveryView as View, type Status, type StatusResult } from "../api";
import DeliveryView, { type StatusActions } from "../components/DeliveryView";
import DestinationCard from "../components/DestinationCard";
import { inputClass, Message, secondaryButton, type Note } from "../components/ui";

// The rider's page, one round at a time (the round is in the URL, never in browser storage):
// the destination card from 2C for rounds they take part in, then (since 3A) their own
// deliveries for that round in the saved route order, and (since 3B) their own status changes.
export default function RiderPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [params, setParams] = useSearchParams();
  const [rounds, setRounds] = useState<DeliveryRoundSummary[] | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const current = useRef<string | null>(null);
  const viewAc = useRef<AbortController | null>(null);
  // Status changes (3B): one save at a time; the screen changes only when the server confirms.
  const [saving, setSaving] = useState<StatusActions["saving"]>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ item: DeliveryItem; target: Status; message: string } | null>(null);
  const [note, setNote] = useState<Note>(null);
  const savingRef = useRef(false);

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
    setView(null); setError(null); setNote(null); setFailed(null); setConfirming(null);
    loadView(roundId);
    return () => { viewAc.current?.abort(); viewAc.current = null; };
  }, [roundId, loadView]);

  const refresh = useCallback(() => {
    if (!roundId) return;
    loadView(roundId);
    loadRounds().catch(fail("Could not load your rounds."));
  }, [roundId, loadView, loadRounds, fail]);

  /** Save one status change. Duplicate taps are ignored while a save is in flight; a retry
   * sends the same expected version, and the server treats a repeat as "already done". */
  const change = useCallback(async (item: DeliveryItem, target: Status) => {
    if (savingRef.current || !roundId) return;
    const id = roundId;
    savingRef.current = true;
    setSaving({ id: item.id, target }); setNote(null); setFailed(null);
    try {
      const res = await api<StatusResult>(`/api/rider/orders/${item.id}/status`, {
        method: "POST", json: { status: target, expected_version: item.version },
      });
      if (current.current !== id || res.view.round_id !== id) return;  // the rider moved to another round
      viewAc.current?.abort();  // an older load must not replace this newer, server-confirmed view
      setView(res.view); setConfirming(null);
      setNote({ kind: "ok", text: res.changed ? `${item.order_code} saved as ${target}.` : `${item.order_code} was already ${target}; nothing changed.` });
      loadRounds().catch(() => undefined);  // picker counts; the list itself is already current
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return onUnauthorized();
      if (current.current !== id) return;
      setConfirming(null);
      if (e instanceof ApiError && e.status < 500) {
        // Refused (changed elsewhere, reassigned, not allowed, gone): nothing was overwritten.
        setNote({ kind: e.status === 409 ? "warn" : "error", text: e.message });
        loadView(id);
      } else {
        // No answer is not proof of failure: the server may have saved it. Retry is safe (a repeat is "already done").
        setFailed({ item, target, message: "Could not confirm the save; showing the last confirmed status. The change may or may not have reached the server. Check your connection and retry; if it was already saved, nothing changes twice." });
      }
    } finally {
      savingRef.current = false;
      setSaving(null);
    }
  }, [roundId, loadView, loadRounds, onUnauthorized]);

  const actions: StatusActions = {
    saving, confirming, failed: failed && { id: failed.item.id, target: failed.target, message: failed.message },
    change: (item, target) => { void change(item, target); },
    confirm: (oid) => { setConfirming(oid); setFailed(null); },
    retry: () => { if (failed) void change(failed.item, failed.target); },
  };

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
        <Message note={note} />
        {view && view.round_id === roundId ? <DeliveryView view={view} actions={actions} /> : !error && <p role="status" className="text-slate-500">Loading deliveries…</p>}
      </section>
    </div>
  );
}
