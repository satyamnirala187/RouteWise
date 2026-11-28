import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router";
import { loadSession, logout, type SessionInfo } from "./api";
import Shell from "./components/Shell";
import ConnectPage from "./pages/ConnectPage";
import ImportPage from "./pages/ImportPage";
import LoginPage from "./pages/LoginPage";
import OrdersPage from "./pages/OrdersPage";
import PlanPage from "./pages/PlanPage";
import RiderPage from "./pages/RiderPage";
import RoundSetupPage from "./pages/RoundSetupPage";
import SettingsPage from "./pages/SettingsPage";

// Route guards only choose which screen to show. Every permission is enforced by the API.
export default function App() {
  const [session, setSession] = useState<SessionInfo | null | undefined>(undefined);
  const [unreachable, setUnreachable] = useState(false);
  const navigate = useNavigate();
  const checking = useRef<AbortController | null>(null);

  // Only a server 401 means "signed out". If the server cannot be reached (or answers unreadably) we cannot tell, so
  // we say so and keep the cookie; we never invent a session and never treat the failure as a logout.
  const check = useCallback(() => {
    checking.current?.abort();
    const ac = (checking.current = new AbortController());
    setUnreachable(false);
    setSession(undefined);
    loadSession(ac.signal).then((s) => { if (!ac.signal.aborted) setSession(s); })
      .catch(() => { if (!ac.signal.aborted) setUnreachable(true); });
  }, []);

  useEffect(() => { check(); return () => checking.current?.abort(); }, [check]);
  useEffect(() => {
    if (!unreachable) return;
    window.addEventListener("online", check);   // the connection came back: look again without a tap
    return () => window.removeEventListener("online", check);
  }, [unreachable, check]);

  const onSignedOut = useCallback(() => {
    setSession(null);
    navigate("/login", { replace: true });
  }, [navigate]);

  const signOut = useCallback(async () => {
    await logout().catch(() => undefined);
    onSignedOut();
  }, [onSignedOut]);

  if (unreachable) return <ConnectPage onRetry={check} />;
  if (session === undefined) {
    return <p className="p-6 text-slate-500" role="status">Loading…</p>;
  }

  const home = session?.role === "admin" ? "/admin" : session?.role === "rider" ? "/rider" : "/login";

  return (
    <Routes>
      <Route path="/login" element={session ? <Navigate to={home} replace /> : <LoginPage onSignedIn={setSession} />} />
      <Route
        path="/admin"
        element={session?.role === "admin" ? <Shell session={session} onSignOut={signOut} /> : <Navigate to={home} replace />}
      >
        <Route index element={<OrdersPage onUnauthorized={onSignedOut} />} />
        <Route path="round" element={<RoundSetupPage onUnauthorized={onSignedOut} />} />
        <Route path="plan" element={<PlanPage onUnauthorized={onSignedOut} />} />
        <Route path="settings" element={<SettingsPage onUnauthorized={onSignedOut} />} />
        <Route path="import" element={<ImportPage onUnauthorized={onSignedOut} />} />
      </Route>
      <Route
        path="/rider"
        element={session?.role === "rider" ? <Shell session={session} onSignOut={signOut} /> : <Navigate to={home} replace />}
      >
        <Route index element={<RiderPage onUnauthorized={onSignedOut} />} />
      </Route>
      <Route path="*" element={<Navigate to={home} replace />} />
    </Routes>
  );
}
