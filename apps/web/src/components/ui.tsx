import type { ReactNode } from "react";
import { KIND_LABEL, type ConfirmationState, type DestinationKind, type RoundSummary } from "../api";

export const inputClass =
  "mt-1 block min-h-11 w-full rounded-md border border-slate-300 bg-white px-3 text-base focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30";
export const primaryButton = "min-h-11 rounded-md bg-brand-600 px-4 font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60";
export const secondaryButton = "min-h-11 rounded-md px-4 font-semibold ring-1 ring-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60";
export const card = "rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200";

export type Note = { kind: "error" | "ok" | "warn"; text: string; details?: string[] } | null;

export function Message({ note, onReload, reloadLabel = "Reload the latest version" }: { note: Note; onReload?: () => void; reloadLabel?: string }) {
  if (!note) return null;
  const style = note.kind === "error" ? "bg-red-50 text-red-800" : note.kind === "warn" ? "bg-orange-50 text-orange-900" : "bg-emerald-50 text-emerald-900";
  return (
    <div role={note.kind === "error" ? "alert" : "status"} className={`rounded-md px-3 py-2 text-sm ${style}`}>
      <p>{note.text}</p>
      {note.details && note.details.length > 0 && (
        <ul className="mt-1 list-disc pl-5">{note.details.map((d) => <li key={d}>{d}</li>)}</ul>
      )}
      {onReload && (
        <button type="button" onClick={onReload} className="mt-2 min-h-11 rounded-md bg-white px-3 font-semibold ring-1 ring-current">
          {reloadLabel}
        </button>
      )}
    </div>
  );
}

export function RoundPicker({ rounds, roundId, onSelect }: { rounds: RoundSummary[]; roundId: string | null; onSelect: (id: string) => void }) {
  return (
    <label className="block min-w-0 text-sm font-medium sm:w-auto">Round
      <select className={`${inputClass} sm:max-w-md`} value={roundId ?? ""} onChange={(e) => onSelect(e.target.value)}>
        {rounds.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.orders})</option>)}
      </select>
    </label>
  );
}

const confirmationStyle: Record<ConfirmationState, string> = {
  confirmed: "bg-emerald-100 text-emerald-900",
  not_confirmed: "bg-amber-100 text-amber-900",
  outdated: "bg-red-100 text-red-800",
};
export const CONFIRMATION_LABEL: Record<ConfirmationState, string> = {
  confirmed: "Confirmed",
  not_confirmed: "Not confirmed",
  outdated: "Outdated — must confirm again",
};

export function ConfirmationBadge({ state }: { state: ConfirmationState }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${confirmationStyle[state]}`} data-testid="confirmation">{CONFIRMATION_LABEL[state]}</span>;
}

/** Admin-side destination label: Home and Custom are named, never located. */
export function destinationLabel(kind: DestinationKind | null | undefined): string {
  if (!kind) return "Not chosen yet";
  if (kind === "home") return "Home (private)";
  if (kind === "custom") return "Custom (private)";
  if (kind === "last_stop") return "Last stop (route ends at the final delivery)";
  return KIND_LABEL[kind];
}

export function Section({ title, children, actions, testId }: { title: string; children: ReactNode; actions?: ReactNode; testId?: string }) {
  return (
    <section className={card} data-testid={testId} aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function parseCoords(text: string): [number, number] | null {
  const m = text.trim().match(/^(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = Number(m[1]), lng = Number(m[2]);
  return Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? [lat, lng] : null;
}

export const COORD_HELP = "Latitude, longitude in decimal degrees, inside DU North Campus — for example 28.6951, 77.2147. Copy them from a dropped pin in Google Maps.";
