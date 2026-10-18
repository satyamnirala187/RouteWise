import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { api, ApiError, type RoundSummary } from "./api";

/** The selected round lives in the URL (`?round=`), never in browser storage. Without a
 * parameter the newest round is shown, as on the Phase 1 Orders page. */
export function useRounds(onError: (e: unknown) => void) {
  const [params, setParams] = useSearchParams();
  const [rounds, setRounds] = useState<RoundSummary[] | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    api<RoundSummary[]>("/api/admin/rounds", { signal: ac.signal }).then(setRounds).catch((e) => {
      if (!ac.signal.aborted) onError(e);
    });
    return () => ac.abort();
  }, [onError]);

  const requested = params.get("round");
  const roundId = rounds ? (rounds.find((r) => r.id === requested)?.id ?? rounds[0]?.id ?? null) : null;
  const select = useCallback((id: string) => {
    setParams((p) => { const next = new URLSearchParams(p); next.set("round", id); return next; });
  }, [setParams]);
  return { rounds, roundId, select };
}

/** One error policy for admin and rider pages: 401 ends the session; aborted requests are
 * ignored; anything else becomes a message. */
export function useErrorHandler(onUnauthorized: () => void, setError: (m: string | null) => void, fallback: string) {
  return useCallback((e: unknown) => {
    if (e instanceof DOMException && e.name === "AbortError") return;
    if (e instanceof ApiError && e.status === 401) return onUnauthorized();
    setError(e instanceof ApiError ? e.message : fallback);
  }, [onUnauthorized, setError, fallback]);
}
