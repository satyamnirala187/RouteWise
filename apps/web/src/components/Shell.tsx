import { NavLink, Outlet, useSearchParams } from "react-router";
import type { SessionInfo } from "../api";

const link = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-11 items-center rounded-md px-3 py-2 text-sm font-medium ${isActive ? "bg-white/15 text-white" : "text-white/80 hover:text-white"}`;

export default function Shell({ session, onSignOut }: { session: SessionInfo; onSignOut: () => void }) {
  // Round-scoped pages keep the selected round when you move between them.
  const [params] = useSearchParams();
  const round = params.get("round");
  const withRound = (path: string) => (round ? `${path}?round=${encodeURIComponent(round)}` : path);
  return (
    <div className="min-h-dvh">
      <header className="bg-brand-700 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-3">
          <span className="mr-2 text-lg font-semibold">RouteWise</span>
          {session.role === "admin" ? (
            <nav className="flex flex-wrap gap-1" aria-label="Main">
              <NavLink to={withRound("/admin")} end className={link}>Orders</NavLink>
              <NavLink to={withRound("/admin/round")} className={link}>Round setup</NavLink>
              <NavLink to={withRound("/admin/plan")} className={link}>Plan</NavLink>
              <NavLink to="/admin/import" className={link}>Import</NavLink>
              <NavLink to="/admin/settings" className={link}>Office &amp; riders</NavLink>
            </nav>
          ) : (
            <nav className="flex gap-1" aria-label="Main">
              <NavLink to="/rider" end className={link}>My deliveries</NavLink>
            </nav>
          )}
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="hidden sm:inline" data-testid="whoami">
              {session.rider_name ?? session.username} · {session.role === "admin" ? "Admin" : "Rider"}
            </span>
            <button type="button" onClick={onSignOut}
              className="min-h-11 rounded-md bg-white/15 px-3 py-2 font-medium hover:bg-white/25 focus-visible:outline-2 focus-visible:outline-white">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-5">
        <Outlet />
      </main>
    </div>
  );
}
