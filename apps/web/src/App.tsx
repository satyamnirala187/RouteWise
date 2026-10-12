import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router";
import { loadSession, logout, type SessionInfo } from "./api";
import Shell from "./components/Shell";
import ImportPage from "./pages/ImportPage";
import LoginPage from "./pages/LoginPage";
import OrdersPage from "./pages/OrdersPage";
import RiderPage from "./pages/RiderPage";

// Route guards only choose which screen to show. Every permission is enforced by the API.
export default function App() {
  const [session, setSession] = useState<SessionInfo | null | undefined>(undefined);
  const navigate = useNavigate();

  useEffect(() => {
    loadSession().then(setSession).catch(() => setSession(null));
  }, []);

  const onSignedOut = useCallback(() => {
    setSession(null);
    navigate("/login", { replace: true });
  }, [navigate]);

  const signOut = useCallback(async () => {
    await logout().catch(() => undefined);
    onSignedOut();
  }, [onSignedOut]);

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
