import type { ReactNode } from "react";
import { KIND_LABEL, VEHICLE_LABEL, type DeliveryItem, type DeliveryPlace, type DeliveryView as View, type Status } from "../api";
import { directionsLink, telLink } from "../links";
import { km, trafficFree } from "../planning";
import { card } from "./ui";

// The rider's own deliveries for one round (3A). Pending orders follow the round's CURRENT saved
// plan; an out-of-date plan is shown as the saved order, never as a new route. Call and Navigate
// are plain links the rider taps; nothing is opened or marked automatically. Since 3B each card
// offers the rider's own status changes; the page saves them one at a time and shows the result
// only once the server has confirmed it.

/** Status actions, owned by the page (one save at a time). */
export interface StatusActions {
  saving: { id: string; target: Status } | null;  // the one save in flight; every status button waits
  confirming: string | null;                       // order id awaiting "Yes, delivered"
  failed: { id: string; target: Status; message: string } | null;  // save not confirmed (network); retry offered
  change: (item: DeliveryItem, target: Status) => void;
  confirm: (id: string | null) => void;
  retry: () => void;
}

const statusButton = "inline-flex min-h-11 items-center justify-center rounded-md px-4 font-semibold disabled:cursor-not-allowed disabled:opacity-60";

const actionLink = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 font-semibold";

function placeText(p: DeliveryPlace | null | undefined, own = false): string {
  if (!p) return "Not chosen yet";
  if (p.kind === "home" || p.kind === "custom") return own ? `${KIND_LABEL[p.kind]} (your saved location)` : KIND_LABEL[p.kind];
  if (p.kind === "last_stop") return "Last stop — the route ends at your final delivery";
  return p.label && p.label !== KIND_LABEL[p.kind] ? `${KIND_LABEL[p.kind]} — ${p.label}` : KIND_LABEL[p.kind];
}

export default function DeliveryView({ view, actions }: { view: View; actions?: StatusActions }) {
  const { plan, setup } = view;
  const route = plan?.route ?? null;
  const pendingCount = view.sequence.reduce((n, s) => n + s.orders.length, 0) + view.unsequenced.length;
  const total = pendingCount + view.postponed.length + view.completed.length;
  const ownSetupChanged = !!setup && setup.confirmation !== "confirmed";
  const endsDiffer = !!route && !!setup && (route.start.kind !== setup.start.kind || route.destination.kind !== setup.destination?.kind);

  return (
    <div className="space-y-4" data-testid="delivery-view" data-round={view.round_id}>
      <section className={card} aria-labelledby="plan-status-title" data-testid="plan-status">
        <h3 id="plan-status-title" className="text-lg font-semibold">Route</h3>
        {!plan ? (
          <p className="mt-1 text-sm text-slate-700" data-testid="no-plan">
            No route has been planned for this round yet. Your admin plans it after every rider has confirmed their setup.
          </p>
        ) : (
          <div className="mt-1 space-y-2 text-sm">
            <p data-testid="plan-version">
              <span className="font-semibold">Plan version {plan.version}</span>{" "}
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-900">Current</span>{" "}
              <span className="text-slate-600">saved {new Date(plan.created_at).toLocaleString()}</span>
            </p>
            {plan.superseded_versions > 0 && (
              <p className="text-slate-600">
                It replaces {plan.superseded_versions === 1 ? "version 1" : `versions 1–${plan.version - 1}`}, which {plan.superseded_versions === 1 ? "is" : "are"} superseded and not used.
              </p>
            )}
            {plan.out_of_date && (
              <div role="alert" data-testid="plan-out-of-date" className="rounded-lg bg-amber-50 px-3 py-2 text-amber-950 ring-1 ring-amber-300">
                <p className="font-semibold">This route is out of date.</p>
                <p>Something changed after it was planned (for example a destination, capacity or order). The order below is the saved order from version {plan.version}; it has not been re-optimized.</p>
                <p className="mt-1 font-medium">
                  {ownSetupChanged ? "Confirm your setup above, then ask your admin to optimize the round again." : "Ask your admin to optimize the round again."}
                </p>
              </div>
            )}
            {plan.progress_since_plan && !plan.out_of_date && (
              <p className="text-slate-600" data-testid="progress-since-plan">
                Deliveries have been updated since this plan was saved. The remaining stops keep their saved order.
              </p>
            )}
            {!route && <p className="text-slate-700" data-testid="no-route">The current plan has no route for you.</p>}
          </div>
        )}
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-testid="route-ends">
          <dt className="font-medium text-slate-600">Start</dt>
          <dd>{setup ? placeText(setup.start) : route ? placeText(route.start) : "—"}</dd>
          <dt className="font-medium text-slate-600">Destination</dt>
          <dd>{setup ? placeText(setup.destination, true) : route ? placeText(route.destination, true) : "—"}</dd>
          {(setup || route) && <><dt className="font-medium text-slate-600">Vehicle</dt><dd>{VEHICLE_LABEL[(setup ?? route)!.vehicle]}</dd></>}
        </dl>
        {endsDiffer && route && (
          <p className="mt-2 text-sm text-amber-900" data-testid="planned-ends">
            The saved route was planned from {placeText(route.start)} to {placeText(route.destination, true)}.
          </p>
        )}
        {!setup && (
          <p className="mt-2 text-sm text-slate-600">You are no longer part of this round's setup; the orders you still hold are listed below.</p>
        )}
        {route && (
          <p className="mt-2 text-sm text-slate-700" data-testid="route-distance">
            Planned road distance for the whole saved route {km(route.road_distance_m)}, {trafficFree(route.road_duration_s)}
            {plan!.out_of_date ? " — for the saved, out-of-date order" : ""}. This is the plan, not the distance left.
          </p>
        )}
      </section>

      {total === 0 ? (
        <p className={`${card} text-slate-600`} data-testid="no-deliveries">
          No deliveries are assigned to you in this round yet. They appear here once your admin has planned the round.
        </p>
      ) : (
        <>
          <Section id="sequence" title={plan?.out_of_date ? "Pending deliveries — saved order (out of date)" : "Pending deliveries in route order"}
            count={view.sequence.reduce((n, s) => n + s.orders.length, 0)} testId="sequence"
            note="Call opens your phone's dialer. Navigate opens Google Maps directions to the customer's pin; Google Maps chooses its own road and travel options, which can differ from the planned route and your vehicle. Neither marks a delivery done."
            empty={plan ? "No Pending deliveries in your saved route." : "No route yet."}>
            <ol className="space-y-4">
              {view.sequence.map((stop, i) => stop.orders.map((o) => (
                <OrderCard key={o.id} item={o} stop={stop.seq} next={i === 0} stale={!!plan?.out_of_date} actions={actions} />
              )))}
            </ol>
          </Section>

          {view.unsequenced.length > 0 && (
            <Section id="unsequenced" title="Pending, not in the saved route" count={view.unsequenced.length} testId="unsequenced"
              note={plan ? "These orders are yours but have no position in the current plan's route for you (for example an order returned from Postponed). They need planning: ask your admin to optimize the round again." : "No route has been planned yet, so these orders are listed by order code, not in delivery order."}>
              <ul className="space-y-4">{view.unsequenced.map((o) => <OrderCard key={o.id} item={o} actions={actions} />)}</ul>
            </Section>
          )}
          {view.postponed.length > 0 && (
            <Section id="postponed" title="Postponed" count={view.postponed.length} testId="postponed"
              note="Kept with you, outside the active route order. Return one to Pending when the customer is available; it goes back to its saved stop only if it had one in the current plan.">
              <ul className="space-y-4">{view.postponed.map((o) => <OrderCard key={o.id} item={o} actions={actions} />)}</ul>
            </Section>
          )}
          {view.completed.length > 0 && (
            <Section id="completed" title="Completed" count={view.completed.length} testId="completed">
              <ul className="space-y-3">{view.completed.map((o) => <OrderCard key={o.id} item={o} />)}</ul>
            </Section>
          )}
        </>
      )}
    </div>
  );
}

function Section({ id, title, count, testId, note, empty, children }: {
  id: string; title: string; count: number; testId: string; note?: string; empty?: string; children: ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-title`} data-testid={testId} className="space-y-2">
      <h3 id={`${id}-title`} className="text-lg font-semibold">{title} <span className="text-base font-normal text-slate-500">({count})</span></h3>
      {note && <p className="text-sm text-slate-600">{note}</p>}
      {count === 0 && empty ? <p className="text-sm text-slate-600">{empty}</p> : children}
    </section>
  );
}

const statusBadge: Record<Status, string> = {
  Pending: "bg-amber-50 text-amber-950 ring-amber-400",
  Postponed: "bg-violet-50 text-violet-950 ring-violet-400",
  Completed: "bg-emerald-50 text-emerald-950 ring-emerald-500",
};
const statusDot: Record<Status, string> = { Pending: "bg-amber-500", Postponed: "bg-violet-600", Completed: "bg-emerald-600" };
// A coloured edge per status; the badge text carries the meaning, so colour is never the only cue.
const statusEdge: Record<Status, string> = { Pending: "border-l-amber-400", Postponed: "border-l-violet-500", Completed: "border-l-emerald-500" };

/** The rider card's status: larger than the admin table's pill, with a label for screen readers. */
function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-semibold ring-1 ring-inset ${statusBadge[status]}`} data-testid="status-badge">
      <span aria-hidden="true" className={`size-2 rounded-full ${statusDot[status]}`} />
      <span className="sr-only">Status: </span>{status}
    </span>
  );
}

const detailLabel = "text-xs font-semibold uppercase tracking-wide text-slate-600";

function OrderCard({ item, stop, next = false, stale = false, actions }: {
  item: DeliveryItem; stop?: number; next?: boolean; stale?: boolean; actions?: StatusActions;
}) {
  const call = telLink(item.contact);
  const nav = directionsLink(item.location, item.location_issue);
  const done = item.status === "Completed";
  const frame = next ? "border-l-brand-600 ring-2 ring-brand-600" : `${statusEdge[item.status]} ring-1 ring-slate-300`;
  return (
    <li className={`rounded-xl border-l-[6px] bg-white shadow-sm ${frame} ${done ? "px-4 py-3" : "p-4"}`}
      data-testid="rider-order" data-order={item.order_code} data-status={item.status}>
      <div className="flex flex-wrap items-center gap-2">
        {stop !== undefined && <span className="rounded-md bg-slate-900 px-2.5 py-1 text-sm font-bold text-white" data-testid="stop-number">Stop {stop}</span>}
        {next && <span className="rounded-md bg-brand-600 px-2.5 py-1 text-sm font-bold text-white" data-testid="next-badge">{stale ? "Next in saved order" : "Next"}</span>}
        <span className={stop !== undefined ? "ml-auto" : ""}><StatusBadge status={item.status} /></span>
      </div>
      <p className={`${done ? "mt-2 text-base" : "mt-3 text-lg"} font-semibold leading-snug text-slate-950`} data-testid="customer">{item.customer_name}</p>
      <p className="text-base text-slate-800" data-testid="product"><span className="sr-only">Product: </span>{item.product}</p>
      <p className="mt-0.5 text-xs text-slate-600">Order <span className="font-mono" data-testid="order-code">{item.order_code}</span></p>
      <dl className={done ? "mt-2 space-y-1 text-sm" : "mt-3 divide-y divide-slate-200 rounded-lg bg-slate-50 text-sm ring-1 ring-slate-200"}>
        {item.instructions && (
          <div className={done ? "" : "px-3 py-2"} data-testid="instructions">
            <dt className={done ? "inline font-medium text-slate-700" : detailLabel}>Delivery instructions<span className={done ? "" : "sr-only"}>:</span> </dt>
            <dd className={done ? "inline text-slate-700" : "mt-0.5 text-slate-900"}>{item.instructions}</dd>
          </div>
        )}
        <div className={done ? "" : "px-3 py-2"} data-testid="contact">
          <dt className={done ? "inline font-medium text-slate-700" : detailLabel}>Contact<span className={done ? "" : "sr-only"}>:</span> </dt>
          <dd className={done ? "inline text-slate-700" : "mt-0.5 font-medium tabular-nums text-slate-900"}>{item.contact || "—"}</dd>
        </div>
      </dl>
      {!done && (
        <div className="mt-4" role="group" aria-labelledby={`reach-${item.id}`}>
          <p id={`reach-${item.id}`} className={detailLabel}>Reach the customer</p>
          <div className="mt-1.5 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
            {call.href ? (
              <a href={call.href} className={`${actionLink} bg-brand-600 text-white hover:bg-brand-700`} data-testid="call-link"
                aria-label={`Call ${item.customer_name} (${item.order_code})`}>Call</a>
            ) : (
              <p className="col-span-2 text-sm text-red-800" data-testid="call-unavailable">Calling unavailable: {call.issue}</p>
            )}
            {nav.href ? (
              <a href={nav.href} target="_blank" rel="noopener noreferrer" className={`${actionLink} bg-white text-slate-900 ring-1 ring-slate-400 hover:bg-slate-50`}
                data-testid="navigate-link" aria-label={`Navigate to ${item.customer_name} (${item.order_code}) in Google Maps`}>Navigate</a>
            ) : (
              <p className="col-span-2 text-sm text-red-800" data-testid="navigate-unavailable">Navigation unavailable: {nav.issue}</p>
            )}
          </div>
        </div>
      )}
      {!done && actions && <StatusControls item={item} actions={actions} />}
    </li>
  );
}

const TARGETS: Record<"Pending" | "Postponed", { target: Status; label: string; style: string }[]> = {
  Pending: [
    { target: "Completed", label: "Mark delivered", style: "bg-emerald-700 text-white hover:bg-emerald-800" },
    { target: "Postponed", label: "Postpone", style: "bg-white ring-1 ring-violet-600 text-violet-900 hover:bg-violet-50" },
  ],
  Postponed: [{ target: "Pending", label: "Return to Pending", style: "bg-white ring-1 ring-amber-600 text-amber-950 hover:bg-amber-50" }],
};

/** The rider's status actions for one Pending or Postponed order. Completed needs a second tap,
 * because a rider cannot reopen it. While any save is in flight every button is disabled. */
function StatusControls({ item, actions }: { item: DeliveryItem; actions: StatusActions }) {
  const busy = actions.saving !== null;
  const mine = actions.saving?.id === item.id;
  const failed = actions.failed?.id === item.id ? actions.failed : null;
  if (item.status === "Completed") return null;
  return (
    <div className="mt-4 border-t border-slate-200 pt-3" role="group" aria-labelledby={`status-${item.id}`}>
      <p id={`status-${item.id}`} className={detailLabel}>Update delivery status</p>
      {actions.confirming === item.id ? (
        <div className="mt-1.5 rounded-md bg-emerald-50 p-3 text-sm text-emerald-950 ring-1 ring-emerald-300" data-testid="confirm-delivered">
          <p className="font-medium">Mark {item.order_code} delivered? You cannot undo this yourself.</p>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:flex">
            <button type="button" className={`${statusButton} bg-emerald-700 text-white hover:bg-emerald-800`} disabled={busy}
              aria-busy={mine} onClick={() => actions.change(item, "Completed")}>{mine ? "Saving…" : "Yes, delivered"}</button>
            <button type="button" className={`${statusButton} bg-white ring-1 ring-slate-400 hover:bg-slate-50`} disabled={busy}
              onClick={() => actions.confirm(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="mt-1.5 space-y-2" data-testid="status-actions">
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
            {TARGETS[item.status].map((t, _, all) => (
              <button key={t.target} type="button" className={`${statusButton} ${t.style} ${all.length === 1 ? "col-span-2" : ""}`} disabled={busy}
                aria-busy={mine && actions.saving?.target === t.target}
                aria-label={`${t.label}: ${item.order_code}`}
                onClick={() => (t.target === "Completed" ? actions.confirm(item.id) : actions.change(item, t.target))}>
                {mine && actions.saving?.target === t.target ? "Saving…" : t.label}
              </button>
            ))}
          </div>
          {failed && (
            <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-900 ring-1 ring-red-200" data-testid="status-failed">
              <p>{failed.message}</p>
              <button type="button" className={`${statusButton} mt-2 bg-white ring-1 ring-red-300`} disabled={busy} onClick={actions.retry}>
                Retry: mark {failed.target}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
