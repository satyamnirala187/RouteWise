import { useState, type FormEvent } from "react";
import { api, ApiError, STATUSES, type AdminOrder, type RoundRider, type Status } from "../api";
import { mapsUrl } from "./Badges";

const input =
  "mt-1 block min-h-11 w-full rounded-md border border-slate-300 px-3 text-base focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30";

function parseCoords(text: string): [number, number] | null {
  const m = text.trim().match(/^(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)$/);
  return m ? [Number(m[1]), Number(m[2])] : null;
}

export default function OrderEditor({ order, riders = [], onSaved, onClose, onUnauthorized }: {
  order: AdminOrder;
  riders?: RoundRider[];  // participating riders of the round (owner-lock choices)
  onSaved: (o: AdminOrder) => void;
  onClose: () => void;
  onUnauthorized: () => void;
}) {
  const [form, setForm] = useState({
    customer_name: order.customer_name,
    product: order.product,
    contact: order.contact,
    instructions: order.instructions ?? "",
    status: order.status as Status,
  });
  const [coords, setCoords] = useState(order.location.lat != null ? `${order.location.lat}, ${order.location.lng}` : "");
  const [link, setLink] = useState(order.location_link);
  const [lock, setLock] = useState(order.planning.locked_rider_id ?? "");
  const [priority, setPriority] = useState(order.planning.first_priority);
  const [message, setMessage] = useState<{ kind: "error" | "ok" | "warn"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<AdminOrder>, ok: string) {
    setBusy(true);
    setMessage(null);
    try {
      const updated = await fn();
      onSaved(updated);
      // A pin edit may take the order out of its stop group (4C); say so, with the usual result.
      const text = [updated.warning ?? ok, updated.stop_group_notice].filter(Boolean).join(" ");
      setMessage(updated.warning || updated.stop_group_notice ? { kind: "warn", text } : { kind: "ok", text });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return onUnauthorized();
      const details = e instanceof ApiError && e.details.length ? ` (${e.details.join(", ")})` : "";
      setMessage({ kind: "error", text: (e instanceof ApiError ? e.message : "Save failed.") + details });
    } finally {
      setBusy(false);
    }
  }

  function saveDetails(e: FormEvent) {
    e.preventDefault();
    const instructions = form.instructions.trim();
    run(() => api<AdminOrder>(`/api/admin/orders/${order.id}`, {
      method: "PATCH",
      json: {
        version: order.version,
        customer_name: form.customer_name,
        product: form.product,
        contact: form.contact,
        status: form.status,
        ...(instructions ? { instructions } : { clear_instructions: true }),
      },
    }), "Saved.");
  }

  function savePin(e: FormEvent) {
    e.preventDefault();
    const c = parseCoords(coords);
    if (!c) return setMessage({ kind: "error", text: "Enter coordinates as latitude, longitude (e.g. 28.6883, 77.2148)." });
    run(() => api<AdminOrder>(`/api/admin/orders/${order.id}/pin`, {
      method: "POST", json: { version: order.version, lat: c[0], lng: c[1] },
    }), "Pin saved.");
  }

  function checkLink(e: FormEvent) {
    e.preventDefault();
    run(() => api<AdminOrder>(`/api/admin/orders/${order.id}/location-link`, {
      method: "POST", json: { version: order.version, link },
    }), "Link checked.");
  }

  function savePlanning(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      let current = order;
      if ((current.planning.locked_rider_id ?? "") !== lock) {
        current = await api<AdminOrder>(`/api/admin/orders/${order.id}/lock`, {
          method: "PUT", json: { version: current.version, rider_id: lock || null },
        });
        onSaved(current);
      }
      if (current.planning.first_priority !== priority) {
        current = await api<AdminOrder>(`/api/admin/orders/${order.id}/priority`, {
          method: "PUT", json: { version: current.version, first_priority: priority },
        });
      }
      return current;
    }, "Planning settings saved.");
  }

  const names = Object.fromEntries(riders.map((r) => [r.rider_id, r.display_name]));
  const assigned = order.planning.assigned_rider_id;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="space-y-4 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200" data-testid="order-editor">
      <form onSubmit={saveDetails} className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">Name<input className={input} value={form.customer_name} onChange={set("customer_name")} required /></label>
        <label className="text-sm font-medium">Product<input className={input} value={form.product} onChange={set("product")} required /></label>
        <label className="text-sm font-medium">Contact<input className={input} value={form.contact} onChange={set("contact")} inputMode="tel" required /></label>
        <label className="text-sm font-medium">Status
          <select className={input} value={form.status} onChange={set("status")}>
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className="text-sm font-medium sm:col-span-2">Delivery instructions (optional)
          <textarea className={`${input} py-2`} rows={2} value={form.instructions} onChange={set("instructions")} />
        </label>
        <div className="flex gap-2 sm:col-span-2">
          <button disabled={busy} className="min-h-11 rounded-md bg-brand-600 px-4 font-semibold text-white disabled:opacity-60">Save details</button>
          <button type="button" onClick={onClose} className="min-h-11 rounded-md px-4 font-medium text-slate-700 ring-1 ring-slate-300">Close</button>
        </div>
      </form>

      <div className="space-y-3 border-t border-slate-200 pt-3">
        <h3 className="text-sm font-semibold">Location</h3>
        {order.location.state !== "resolved" && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
            Needs a pin: {order.location.note}. Planning stays blocked until this is fixed.
          </p>
        )}
        <form onSubmit={savePin} className="flex flex-wrap items-end gap-2">
          <label className="min-w-56 flex-1 text-sm font-medium">Set pin manually (latitude, longitude)
            <input className={input} value={coords} onChange={(e) => setCoords(e.target.value)} placeholder="28.6883, 77.2148" />
          </label>
          <button disabled={busy} className="min-h-11 rounded-md bg-slate-800 px-4 font-semibold text-white disabled:opacity-60">Save pin</button>
        </form>
        <form onSubmit={checkLink} className="flex flex-wrap items-end gap-2">
          <label className="min-w-56 flex-1 text-sm font-medium">Or replace the Google Maps link
            <input className={input} value={link} onChange={(e) => setLink(e.target.value)} />
          </label>
          <button disabled={busy} className="min-h-11 rounded-md px-4 font-semibold ring-1 ring-slate-400 disabled:opacity-60">Check link</button>
        </form>
        {order.location.lat != null && order.location.lng != null && (
          <a className="inline-block text-sm font-medium text-brand-700 underline" target="_blank" rel="noopener noreferrer"
            href={mapsUrl(order.location.lat, order.location.lng)}>Check this pin in Google Maps ↗</a>
        )}
      </div>
      <form onSubmit={savePlanning} className="space-y-3 border-t border-slate-200 pt-3" aria-label="Planning">
        <h3 className="text-sm font-semibold">Planning</h3>
        <p className="text-sm text-slate-700" data-testid="assigned-rider">
          Assigned rider (from the current plan): <b>{assigned ? names[assigned] ?? "a rider not in this round" : "none yet"}</b>
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium">Owner lock
            <select className={input} value={lock} onChange={(e) => setLock(e.target.value)} aria-describedby={`lock-help-${order.id}`}>
              <option value="">No lock (the optimizer chooses)</option>
              {riders.map((r) => <option key={r.rider_id} value={r.rider_id}>Lock to {r.display_name}</option>)}
            </select>
            <span id={`lock-help-${order.id}`} className="mt-1 block text-xs font-normal text-slate-600">
              A lock keeps this order with that rider in every mode; manual mode needs one on every Pending order.
            </span>
          </label>
          <label className="flex min-h-11 items-center gap-2 self-center text-sm font-medium">
            <input type="checkbox" className="size-5" checked={priority} onChange={(e) => setPriority(e.target.checked)}
              disabled={order.status !== "Pending" && !order.planning.first_priority} />
            First delivery of its rider's route
          </label>
        </div>
        <button disabled={busy} className="min-h-11 rounded-md bg-slate-800 px-4 font-semibold text-white disabled:opacity-60">Save planning</button>
      </form>
      {message && (
        <p role={message.kind === "error" ? "alert" : "status"}
          className={`rounded-md px-3 py-2 text-sm ${message.kind === "error" ? "bg-red-50 text-red-800" : message.kind === "warn" ? "bg-orange-50 text-orange-900" : "bg-emerald-50 text-emerald-900"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
