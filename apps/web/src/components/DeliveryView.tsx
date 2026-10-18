import type { ReactNode } from "react";
import { KIND_LABEL, VEHICLE_LABEL, type DeliveryItem, type DeliveryPlace, type DeliveryView as View } from "../api";
import { directionsLink, telLink } from "../links";
import { km, trafficFree } from "../planning";
import { StatusPill } from "./Badges";
import { card } from "./ui";

// Step 3A: the rider's own deliveries for one round, read-only. Pending orders follow the round's
// CURRENT saved plan; an out-of-date plan is shown as the saved order, never as a new route.
// Call and Navigate are plain links the rider taps; nothing is opened or marked automatically.

const actionLink = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 font-semibold";

function placeText(p: DeliveryPlace | null | undefined, own = false): string {
  if (!p) return "Not chosen yet";
  if (p.kind === "home" || p.kind === "custom") return own ? `${KIND_LABEL[p.kind]} (your saved location)` : KIND_LABEL[p.kind];
  if (p.kind === "last_stop") return "Last stop — the route ends at your final delivery";
  return p.label && p.label !== KIND_LABEL[p.kind] ? `${KIND_LABEL[p.kind]} — ${p.label}` : KIND_LABEL[p.kind];
}

export default function DeliveryView({ view }: { view: View }) {
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
            Planned road distance {km(route.road_distance_m)}, {trafficFree(route.road_duration_s)}{plan!.out_of_date ? " — for the saved, out-of-date order" : ""}.
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
            <ol className="space-y-3">
              {view.sequence.map((stop, i) => stop.orders.map((o) => (
                <OrderCard key={o.id} item={o} stop={stop.seq} next={i === 0} stale={!!plan?.out_of_date} />
              )))}
            </ol>
          </Section>

          {view.unsequenced.length > 0 && (
            <Section id="unsequenced" title="Pending, not in the saved route" count={view.unsequenced.length} testId="unsequenced"
              note={plan ? "These orders are yours but are not in the current plan's route for you. Ask your admin to optimize the round again." : "No route has been planned yet, so these orders are listed by order code, not in delivery order."}>
              <ul className="space-y-3">{view.unsequenced.map((o) => <OrderCard key={o.id} item={o} />)}</ul>
            </Section>
          )}
          {view.postponed.length > 0 && (
            <Section id="postponed" title="Postponed" count={view.postponed.length} testId="postponed"
              note="Kept with you, outside the active route order.">
              <ul className="space-y-3">{view.postponed.map((o) => <OrderCard key={o.id} item={o} />)}</ul>
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

function OrderCard({ item, stop, next = false, stale = false }: { item: DeliveryItem; stop?: number; next?: boolean; stale?: boolean }) {
  const call = telLink(item.contact);
  const nav = directionsLink(item.location, item.location_issue);
  const done = item.status === "Completed";
  return (
    <li className={`${card} ${next ? "ring-2 ring-brand-600" : ""}`} data-testid="rider-order" data-order={item.order_code} data-status={item.status}>
      <div className="flex flex-wrap items-center gap-2">
        {stop !== undefined && <span className="rounded-md bg-slate-900 px-2 py-0.5 text-xs font-bold text-white" data-testid="stop-number">Stop {stop}</span>}
        {next && <span className="rounded-full bg-brand-600 px-2 py-0.5 text-xs font-semibold text-white" data-testid="next-badge">{stale ? "Next in saved order" : "Next"}</span>}
        <StatusPill status={item.status} />
        <span className="ml-auto font-mono text-xs text-slate-500" data-testid="order-code">{item.order_code}</span>
      </div>
      <p className="mt-2 text-base font-semibold" data-testid="customer">{item.customer_name}</p>
      <p className="text-sm text-slate-700" data-testid="product"><span className="sr-only">Product: </span>{item.product}</p>
      {item.instructions && (
        <p className="mt-2 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-800 ring-1 ring-slate-200" data-testid="instructions">
          <span className="font-medium">Delivery instructions:</span> {item.instructions}
        </p>
      )}
      <p className="mt-2 text-sm text-slate-700" data-testid="contact"><span className="font-medium">Contact:</span> {item.contact || "—"}</p>
      {!done && (
        <div className="mt-3 grid gap-2 sm:flex sm:flex-wrap">
          {call.href ? (
            <a href={call.href} className={`${actionLink} bg-brand-600 text-white hover:bg-brand-700`} data-testid="call-link"
              aria-label={`Call ${item.customer_name} (${item.order_code})`}>Call</a>
          ) : (
            <p className="text-sm text-red-800" data-testid="call-unavailable">Calling unavailable: {call.issue}</p>
          )}
          {nav.href ? (
            <a href={nav.href} target="_blank" rel="noopener noreferrer" className={`${actionLink} ring-1 ring-slate-300 hover:bg-slate-50`}
              data-testid="navigate-link" aria-label={`Navigate to ${item.customer_name} (${item.order_code}) in Google Maps`}>Navigate</a>
          ) : (
            <p className="text-sm text-red-800" data-testid="navigate-unavailable">Navigation unavailable: {nav.issue}</p>
          )}
        </div>
      )}
    </li>
  );
}
