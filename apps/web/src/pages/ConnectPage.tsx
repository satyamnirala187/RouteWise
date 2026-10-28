/** The server could not be reached (or did not give a readable answer) when the app started. This is NOT a sign-out: we do not
 * know the session state, so nothing is signed out and no session is assumed. Deliveries are not kept on this device yet. */
export default function ConnectPage({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex min-h-dvh items-center justify-center p-4">
      <div role="status" data-testid="connect-screen" className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <h1 className="text-2xl font-semibold">Connect to load your deliveries</h1>
        <p className="text-sm text-slate-700">
          RouteWise cannot reach the server right now. Your deliveries are not saved on this device, so they cannot be shown until you are connected.
        </p>
        <p className="text-sm text-slate-600">You have not been signed out. Check your connection and try again.</p>
        <button type="button" onClick={onRetry} className="min-h-11 w-full rounded-md bg-brand-600 px-4 font-semibold text-white hover:bg-brand-700">
          Try again
        </button>
      </div>
    </div>
  );
}
