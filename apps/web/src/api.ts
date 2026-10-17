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
  return status === 401 ? "Please sign in again." : `Request failed (${status}).`;
}

export async function api<T>(path: string, opts: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
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
  const res = await fetch(path, { method, headers, body, credentials: "same-origin", cache: "no-store" });
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
}

export interface RoundSummary { id: string; name: string; created_at: string; orders: number; needs_pin: number; }
export interface ConfigurationBlocker { code: string; reason: string; rider_id?: string; rider?: string; }
export interface Readiness {
  ready: boolean;                // orders and rider setup both ready for planning
  orders: number;
  orders_ready: boolean;         // every order has a valid pin
  blockers: { order_code: string; reason: string }[];  // order-location blockers (Phase 1)
  configuration_blockers: ConfigurationBlocker[];      // riders, depots, destinations, confirmations (Phase 2A)
  riders: { participating: number; confirmed: number };
  input_version: number;
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

export interface RiderOrder {
  id: string;
  order_code: string;
  customer_name: string;
  product: string;
  contact: string;
  instructions: string | null;
  lat: number | null;
  lng: number | null;
  status: Status;
}
