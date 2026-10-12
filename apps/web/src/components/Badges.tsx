import type { LocationInfo, Status } from "../api";

const statusStyle: Record<Status, string> = {
  Pending: "bg-amber-100 text-amber-900",
  Postponed: "bg-violet-100 text-violet-900",
  Completed: "bg-emerald-100 text-emerald-900",
};

export function StatusPill({ status }: { status: Status }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyle[status]}`}>{status}</span>;
}

export function LocationBadge({ location }: { location: LocationInfo }) {
  if (location.state !== "resolved") {
    return <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">Needs pin</span>;
  }
  if (location.in_service_area === false) {
    return <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-semibold text-orange-900">Outside area</span>;
  }
  return <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-900">Pinned</span>;
}

export function mapsUrl(lat: number, lng: number) {
  return `https://www.google.com/maps?q=${lat.toFixed(6)},${lng.toFixed(6)}`;
}
