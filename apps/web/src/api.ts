// Thin API client. The session cookie is HttpOnly and handled by the browser; this module
// only keeps the per-session CSRF token in memory and sends it on every mutating request.
// Nothing is written to localStorage/sessionStorage (customer data must not persist here).

export type Role = "admin" | "rider";
export interface SessionInfo {
  username: string;
  role: Role;
  rider_name: string | null;
  csrf_token: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
  /** Machine-readable code of a structured error (e.g. "NOT_READY", "configuration_changed"). */
  get code(): string | undefined {
    const d = this.detail as { code?: unknown } | undefined;
    return d && typeof d === "object" && typeof d.code === "string" ? d.code : undefined;
  }
  /** Order codes / rider names a structured error refers to (never coordinates). */
  get details(): string[] {
    const d = this.detail as { details?: unknown; issues?: { reason?: string }[] } | undefined;
    if (d && typeof d === "object") {
      if (Array.isArray(d.details)) return d.details.map(String);
      if (Array.isArray(d.issues)) return d.issues.map((i) => String(i.reason ?? ""));
    }
    return [];
  }
}

let csrfToken: string | null = null;
export const setCsrfToken = (token: string | null) => { csrfToken = token; };
export const getCsrfToken = () => csrfToken;

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function messageFrom(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Some fields are invalid.";
  if (detail && typeof detail === "object" && "file_errors" in detail) {
    return (detail as { file_errors: string[] }).file_errors.join(" ");
  }
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  return status === 401 ? "Please sign in again." : `Request failed (${status}).`;
}

export async function api<T>(path: string, opts: { method?: string; json?: unknown; form?: FormData; signal?: AbortSignal } = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  if (MUTATING.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(path, { method, headers, body, credentials: "same-origin", cache: "no-store", signal: opts.signal });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, messageFrom(data?.detail, res.status), data?.detail);
  return data as T;
}

export async function loadSession(): Promise<SessionInfo | null> {
  try {
    const s = await api<SessionInfo>("/api/auth/session");
    setCsrfToken(s.csrf_token);
    return s;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw e;
  }
}

export async function login(username: string, password: string): Promise<SessionInfo> {
  await api("/api/auth/login", { method: "POST", json: { username, password } });
  const s = await loadSession();
  if (!s) throw new ApiError(401, "Sign-in failed");
  return s;
}

export async function logout(): Promise<void> {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } finally {
    setCsrfToken(null);
  }
}

// ---- domain types
export type Status = "Pending" | "Postponed" | "Completed";
export const STATUSES: Status[] = ["Pending", "Postponed", "Completed"];

export interface LocationInfo {
  state: "resolved" | "needs_correction";
  lat: number | null;
  lng: number | null;
  source: string | null;
  note: string | null;
  in_service_area: boolean | null;
}

export interface AdminOrder {
  id: string;
  order_code: string;
  round_id: string;
  source_row: number;
  customer_name: string;
  product: string;
  contact: string;
  instructions: string | null;
  location_link: string;
  location: LocationInfo;
  status: Status;
  version: number;
  warning?: string;
  // Phase 2B planning inputs and current owner (no planning screens yet; 2C)
  planning: { locked_rider_id: string | null; first_priority: boolean; assigned_rider_id: string | null };
}

export interface RoundSummary { id: string; name: string; created_at: string; orders: number; needs_pin: number; }
export interface ConfigurationBlocker { code: string; reason: string; rider_id?: string; rider?: string; }
export type Mode = "equal" | "smart" | "manual";
export interface PlanningLimits { max_pending_orders: number; max_riders: number; max_locations: number; solve_seconds: number; }
export interface Readiness {
  ready: boolean;                // orders and rider setup both ready for planning
  orders: number;
  orders_ready: boolean;         // every order has a valid pin
  blockers: { order_code: string; reason: string }[];  // order-location blockers (Phase 1)
  configuration_blockers: ConfigurationBlocker[];      // riders, depots, destinations, confirmations (Phase 2A)
  riders: { participating: number; confirmed: number };
  input_version: number;
  mode: Mode;                    // Phase 2C: shown on the planning screen
  pending_orders: number;
  planning_limits: PlanningLimits;
}

// ---- Phase 2: Office/Warehouse, riders, round setup, destinations (2A contracts)
export type Vehicle = "scooter" | "bike";
export type DepotKind = "office" | "warehouse";
export type DestinationKind = "office" | "warehouse" | "home" | "last_stop" | "custom";
export const DEPOT_KINDS: DepotKind[] = ["office", "warehouse"];
export const DESTINATION_KINDS: DestinationKind[] = ["office", "warehouse", "home", "last_stop", "custom"];
export const PRIVATE_KINDS: DestinationKind[] = ["home", "custom"];
export const KIND_LABEL: Record<DestinationKind, string> = {
  office: "Office", warehouse: "Warehouse", home: "Home", last_stop: "Last stop", custom: "Custom",
};
export const VEHICLE_LABEL: Record<Vehicle, string> = { scooter: "Scooter", bike: "Motorbike" };

export interface Depot {
  kind: DepotKind; label: string; lat: number; lng: number; version: number; updated_at: string;
  in_service_area: boolean; confirmations_invalidated?: number;
}
export type Depots = Record<DepotKind, Depot | null>;
export interface RiderProfile {
  id: string; username: string; display_name: string; default_vehicle: Vehicle | null; account_active: boolean; version: number;
}
export type ConfirmationState = "confirmed" | "not_confirmed" | "outdated";
export interface Confirmation { state: ConfirmationState; confirmed_version: number | null; confirmed_at: string | null; }
export interface SetupIssue { code: string; reason: string; }
/** Admin view of one rider in a round: destination kind only, never Home/Custom coordinates. */
export interface RoundRider {
  rider_id: string; display_name: string; username: string; account_active: boolean; participating: boolean;
  vehicle: Vehicle; capacity: number; start: DepotKind; destination: { kind: DestinationKind } | null;
  config_version: number; confirmation: Confirmation; issues: SetupIssue[];
}
export interface RiderRoundSummary {
  round_id: string; round_name: string; config_version: number; destination_kind: DestinationKind | null;
  confirmation: ConfirmationState;
}
export interface Place { set: boolean; label: string | null; lat: number | null; lng: number | null; }
/** The rider's own setup (includes their own Home/Custom coordinates; shown only to them). */
export interface RiderSetup {
  round_id: string; round_name: string; config_version: number; vehicle: Vehicle; capacity: number;
  start: { kind: DepotKind } & Place;
  destination: ({ kind: DestinationKind; open_route?: boolean } & Partial<Place>) | null;
  confirmation: Confirmation; issues: SetupIssue[];
}

// ---- Phase 2B: runs and versioned plans
export type RunState = "queued" | "running" | "succeeded" | "failed" | "stale" | "interrupted";
export const TERMINAL_RUN_STATES: RunState[] = ["succeeded", "failed", "stale", "interrupted"];
export interface PlanningRun {
  id: string; round_id: string; state: RunState; mode: Mode; input_version: number;
  requested_at: string; started_at: string | null; finished_at: string | null;
  error: { code: string; message: string; details: string[] } | null;
  plan_version: number | null; timings: Record<string, number> | null;
}
export interface PlanOrderRef { id: string; order_code: string; }
export interface PlanRoute {
  rider_id: string; rider: string | null; vehicle: Vehicle; profile: string; capacity: number;
  start: DepotKind; destination: DestinationKind; open_route: boolean;
  road_distance_m: number; road_duration_s: number;
  stops: { seq: number; orders: PlanOrderRef[] }[]; postponed: PlanOrderRef[]; completed: PlanOrderRef[];
}
export interface Provenance {
  provider?: string; real_road?: boolean; recorded?: boolean; profile?: string; requested_at?: string;
  notes?: string; solver_status?: string; solver_strategy?: string; [k: string]: unknown;
}
export interface Plan {
  id: string; round_id: string; version: number; is_current: boolean; input_version: number;
  out_of_date: boolean;           // the saved routes are no longer usable (3B: not set by riders' delivery progress)
  progress_since_plan: boolean;   // only riders' delivery progress since the plan; the remaining sequence is valid
  unplanned_pending: string[];    // Pending orders the current plan does not route (e.g. returned from Postponed)
  mode: Mode; created_at: string; run_id: string; superseded_at: string | null; distance_label: string;
  provenance: Provenance; warnings: string[];
  summary: {
    planned_orders: number; postponed_held: number; completed_held: number;
    completed_without_owner?: string[]; completed_owner_not_participating?: string[];
    ownership_changes: { order_code: string; from_rider: string | null; to_rider: string | null }[];
    total_road_distance_m: number; total_road_duration_s: number;
  };
  routes: PlanRoute[]; attribution: string;
}
export interface PlanVersion {
  version: number; is_current: boolean; out_of_date: boolean; progress_since_plan: boolean; mode: Mode; created_at: string;
  superseded_at: string | null; total_road_distance_m: number | null; planned_orders: number | null;
}

export interface Issue { severity: "error" | "warning"; field: string | null; message: string; }
export interface PreviewRow {
  row: number;
  values: Record<string, string | null>;
  issues: Issue[];
  location: (LocationInfo & { note: string }) | null;
}
export interface ImportPreview {
  id: string;
  state: string;
  filename: string;
  expires_at: string;
  summary: {
    file_errors: string[];
    file_warnings: string[];
    header_row: number | null;
    mapping: Record<string, string>;
    ignored_columns: string[];
    total_rows: number;
    rows_with_errors: number;
    rows_with_warnings: number;
    needs_pin: number;
    can_commit: boolean;
  };
  rows: PreviewRow[];
}

/** Phase 3A delivery view (`/api/rider/delivery-rounds`, `/api/rider/rounds/{id}/deliveries`). */
export interface DeliveryRoundSummary {
  round_id: string; round_name: string; participating: boolean; confirmation: ConfirmationState | null;
  has_plan: boolean; orders: { pending: number; postponed: number; completed: number };
}
export interface DeliveryItem {
  id: string; order_code: string; customer_name: string; product: string; contact: string;
  instructions: string | null; status: Status;
  version: number;  // sent back with a status update (3B)
  location: { lat: number; lng: number } | null;  // only a resolved pin inside the service area
  location_issue: string | null;
}
export interface DeliveryPlace { kind: DestinationKind; label: string | null; }
export interface DeliveryView {
  round_id: string; round_name: string; participating: boolean;
  setup: { start: DeliveryPlace; destination: DeliveryPlace | null; vehicle: Vehicle; confirmation: ConfirmationState } | null;
  plan: {
    version: number; is_current: true; created_at: string; out_of_date: boolean; progress_since_plan: boolean;
    superseded_versions: number;
    real_road: boolean; recorded: boolean;
    route: { vehicle: Vehicle; start: DeliveryPlace; destination: DeliveryPlace; open_route: boolean;
             road_distance_m: number; road_duration_s: number } | null;
  } | null;
  sequence: { seq: number; orders: DeliveryItem[] }[];
  unsequenced: DeliveryItem[]; postponed: DeliveryItem[]; completed: DeliveryItem[];
}
/** `POST /api/rider/orders/{id}/status` (3B). */
export interface StatusResult { changed: boolean; order: DeliveryItem; view: DeliveryView; }
