import { useShellUpdate } from "../offline/shell";

/** A newer build is installed and waiting. It is used the next time the app is opened; nothing changes under the rider's hands. */
export default function UpdateBanner() {
  const apply = useShellUpdate();
  if (!apply) return null;
  return (
    <div role="status" data-testid="shell-update"
      className="fixed inset-x-0 bottom-0 z-50 flex flex-wrap items-center gap-3 bg-slate-900 px-4 py-3 text-sm text-white">
      <p className="flex-1">A new version of RouteWise is ready. It will be used the next time you open the app.</p>
      <button type="button" onClick={apply} className="min-h-11 rounded-md bg-white/15 px-3 py-2 font-medium hover:bg-white/25 focus-visible:outline-2 focus-visible:outline-white">
        Reload to update
      </button>
    </div>
  );
}
