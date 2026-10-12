import { useState, type FormEvent } from "react";
import { ApiError, login, type SessionInfo } from "../api";

export default function LoginPage({ onSignedIn }: { onSignedIn: (s: SessionInfo) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await login(username, password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div>
          <h1 className="text-2xl font-semibold">RouteWise</h1>
          <p className="text-sm text-slate-600">Sign in with the account your admin gave you.</p>
        </div>
        <label className="block text-sm font-medium">
          Username
          <input name="username" autoComplete="username" required value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 block min-h-11 w-full rounded-md border border-slate-300 px-3 text-base focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30" />
        </label>
        <label className="block text-sm font-medium">
          Password
          <input name="password" type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 block min-h-11 w-full rounded-md border border-slate-300 px-3 text-base focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-600/30" />
        </label>
        {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
        <button type="submit" disabled={busy}
          className="min-h-11 w-full rounded-md bg-brand-600 px-4 font-semibold text-white hover:bg-brand-700 disabled:opacity-60">
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-xs text-slate-500">There is no public sign-up. Accounts are created by an administrator.</p>
      </form>
    </div>
  );
}
