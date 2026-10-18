import { KIND_LABEL, VEHICLE_LABEL, type AdminOrder, type Plan } from "../api";
import { km, provenanceLabel, trafficFree } from "../planning";
import { destinationLabel } from "./ui";

/** One saved plan as a list (no map in Phase 2). `title` says whether this is the current plan
 * or a history version, so an older result is never mistaken for a new one. */
export default function PlanView({ plan, title, orders }: { plan: Plan; title: string; orders: Record<string, AdminOrder> }) {
  const s = plan.summary;
  const p = plan.provenance;
  const created = new Date(plan.created_at).toLocaleString();
  return (
    <section className="space-y-4" aria-label={title} data-testid="plan-view" data-version={plan.version}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold">{title}</h2>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-800">Version {plan.version}</span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold capitalize text-slate-800">{plan.mode} mode</span>
        {plan.is_current
          ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-900">Current</span>
          : <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-700">Superseded</span>}
      </div>
      <p className="text-sm text-slate-600">Saved {created}.</p>

      {plan.out_of_date && (
        <div role="status" data-testid="out-of-date" className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-950 ring-1 ring-amber-300">
          <b>Plan out of date.</b> Orders, riders, destinations or the Office/Warehouse changed after this plan was made.
          Riders' assignments are unchanged until you optimize again.
        </div>
      )}
      {plan.progress_since_plan && (
        <p role="status" data-testid="progress-since-plan" className="rounded-lg bg-sky-50 px-4 py-3 text-sm text-sky-950 ring-1 ring-sky-200">
          Riders have updated deliveries since this plan was saved (orders marked Completed, Postponed or back to Pending).
          The remaining saved stops are still valid; the totals below are as planned, not what is left.
        </p>
      )}
      {plan.is_current && plan.unplanned_pending?.length > 0 && (
        <div role="status" data-testid="unplanned-pending" className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-950 ring-1 ring-amber-300">
          <b>{plan.unplanned_pending.length} Pending order(s) are not in this plan's routes:</b> {plan.unplanned_pending.join(", ")}.
          For example, a rider returned a Postponed order to Pending. They need planning: optimize again to place them.
        </div>
      )}

      <div className="grid gap-3 text-sm sm:grid-cols-3">
        <p className="rounded-lg bg-white p-3 ring-1 ring-slate-200"><span className="block text-slate-500">Planned orders</span>
          <b className="text-lg">{s.planned_orders}</b>
          {(s.postponed_held > 0 || s.completed_held > 0) && <span className="block text-xs text-slate-600">plus {s.postponed_held} Postponed and {s.completed_held} Completed kept with their rider</span>}
        </p>
        <p className="rounded-lg bg-white p-3 ring-1 ring-slate-200"><span className="block text-slate-500">Planned total road distance</span>
          <b className="text-lg" data-testid="total-distance">{km(s.total_road_distance_m)}</b></p>
        <p className="rounded-lg bg-white p-3 ring-1 ring-slate-200"><span className="block text-slate-500">Planned total riding time</span>
          <b className="text-lg">{trafficFree(s.total_road_duration_s)}</b></p>
      </div>

      <div className="rounded-lg bg-white p-3 text-sm ring-1 ring-slate-200" data-testid="provenance">
        <p className="font-semibold">{provenanceLabel(p)}</p>
        <p className="text-slate-600">{plan.distance_label}</p>
        {p.solver_status && <p className="text-slate-600">Solver: {p.solver_strategy ?? "OR-Tools"}, status {p.solver_status}.</p>}
        <p className="mt-1 text-xs text-slate-500">{plan.attribution}</p>
      </div>

      {plan.warnings.length > 0 && (
        <div role="status" data-testid="plan-warnings" className="rounded-lg bg-orange-50 px-4 py-3 text-sm text-orange-950 ring-1 ring-orange-200">
          <p className="font-semibold">Warnings</p>
          <ul className="list-disc pl-5">{plan.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}

      {s.ownership_changes.length > 0 && (
        <div className="rounded-lg bg-sky-50 px-4 py-3 text-sm text-sky-950 ring-1 ring-sky-200" data-testid="ownership-changes">
          <p className="font-semibold">Orders that moved to another rider compared with the previous plan</p>
          <ul className="list-disc pl-5">
            {s.ownership_changes.map((c) => <li key={c.order_code}>{c.order_code}: {c.from_rider ?? "?"} → {c.to_rider ?? "?"}</li>)}
          </ul>
        </div>
      )}
      {((s.completed_without_owner?.length ?? 0) > 0 || (s.completed_owner_not_participating?.length ?? 0) > 0) && (
        <p className="text-sm text-slate-600">Completed orders kept as history without a route: {[...(s.completed_without_owner ?? []), ...(s.completed_owner_not_participating ?? [])].join(", ")}.</p>
      )}

      <ol className="grid gap-4 lg:grid-cols-2" aria-label="Routes">
        {plan.routes.map((r) => (
          <li key={r.rider_id} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200" data-testid="plan-route" data-rider={r.rider ?? ""}>
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="mr-auto font-semibold">{r.rider ?? "Rider"}</h3>
              <span className="text-sm text-slate-600">{VEHICLE_LABEL[r.vehicle]} · capacity {r.capacity}</span>
            </div>
            <p className="mt-1 text-sm"><b data-testid="route-distance">{km(r.road_distance_m)}</b> · {trafficFree(r.road_duration_s)}</p>
            <ol className="mt-3 space-y-1 text-sm">
              <li className="text-slate-600" data-testid="route-start">Start: {KIND_LABEL[r.start]}</li>
              {r.stops.map((stop) => (
                <li key={stop.seq} className="flex gap-2" data-testid="route-stop">
                  <span className="w-6 shrink-0 text-right font-mono text-slate-500">{stop.seq}.</span>
                  <span className="min-w-0">{stop.orders.map((o) => (
                    <span key={o.id} className="block">
                      <span className="font-mono text-xs text-slate-500" data-testid="stop-order">{o.order_code}</span>{" "}
                      {orders[o.id] ? `${orders[o.id].customer_name} — ${orders[o.id].product}` : ""}
                    </span>
                  ))}</span>
                </li>
              ))}
              <li className="text-slate-600" data-testid="route-end">
                End: {r.open_route ? "Last stop — the route ends at the final delivery (open route; no return leg counted)" : destinationLabel(r.destination)}
              </li>
            </ol>
            {r.stops.length === 0 && (
              <p className="mt-2 text-sm text-slate-600" data-testid="idle-route">
                No Pending orders for this rider in this plan.
                {r.road_distance_m > 0 && " The distance shown is the road trip from their start to their destination."}
              </p>
            )}
            {(r.postponed.length > 0 || r.completed.length > 0) && (
              <p className="mt-2 text-xs text-slate-600">
                Kept with this rider, not in the sequence:{" "}
                {[...r.postponed.map((o) => `${o.order_code} (Postponed)`), ...r.completed.map((o) => `${o.order_code} (Completed)`)].join(", ")}
              </p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
