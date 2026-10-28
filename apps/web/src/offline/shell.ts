import { useEffect, useState } from "react";

// Registers the app-shell worker (public files only; see src/sw/worker.template.js) and reports a waiting update.
// Nothing here stores or reads customer data. The environment is injectable, as in reroute.ts, so it is unit-tested.

export interface ShellEnv {
  prod: boolean;
  win: Pick<Window, "isSecureContext" | "addEventListener" | "removeEventListener">;
  doc: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;
  nav: { serviceWorker?: ServiceWorkerContainer };
  reload: () => void;
}

const browserEnv = (): ShellEnv => ({ prod: import.meta.env.PROD, win: window, doc: document, nav: navigator, reload: () => window.location.reload() });

/** Only a built app, in a secure context (HTTPS or localhost), in a browser that has service workers. The Vite dev server never registers one. */
export function shellWorkerSupported(env: ShellEnv): boolean {
  return env.prod && env.win.isSecureContext === true && !!env.nav.serviceWorker;
}

/** Registers /sw.js. `onUpdateReady` gets an `apply` function when a newer build is installed and WAITING while an older worker
 * still controls this page. The waiting build takes over only when every tab is closed (next launch) or when `apply` runs;
 * `apply` reloads this page once the new worker is in charge. Returns a cleanup function. */
export function startShellWorker(onUpdateReady: (apply: () => void) => void, env: ShellEnv = browserEnv()): () => void {
  if (!shellWorkerSupported(env)) return () => undefined;
  const sw = env.nav.serviceWorker!;
  let stopped = false;
  let applied = false;
  let registration: ServiceWorkerRegistration | undefined;
  let announced: ServiceWorker | null = null;   // one announcement per waiting build
  let underWorker = !!sw.controller;            // false on the very first visit: nothing is being replaced then

  // Our own "update now" reloads once the new worker is in charge. If ANOTHER tab applied the update, this older page keeps
  // running as it is and is only offered a reload. The first install also changes the controller (it claims the page): nothing
  // is replaced then, but from that moment this page is under a worker, so the next change is a replacement.
  const onControllerChange = () => {
    const replacing = underWorker;
    underWorker = true;
    if (applied) env.reload();
    else if (replacing && !stopped) onUpdateReady(() => env.reload());
  };
  const announce = (reg: ServiceWorkerRegistration) => {
    if (stopped || !reg.waiting || !sw.controller || reg.waiting === announced) return;   // no controller = the first install, not an update
    announced = reg.waiting;
    onUpdateReady(() => { applied = true; reg.waiting?.postMessage({ type: "SKIP_WAITING" }); });
  };
  const check = () => { registration?.update().catch(() => undefined); };   // offline: nothing to check
  const onVisible = () => { if (env.doc.visibilityState === "visible") check(); };

  sw.addEventListener("controllerchange", onControllerChange);
  env.win.addEventListener("online", check);
  env.doc.addEventListener("visibilitychange", onVisible);
  sw.register("/sw.js", { scope: "/" }).then((reg) => {
    registration = reg;
    announce(reg);
    // A build may already be installing (its `updatefound` fired before we could listen) or may start later.
    const watch = (next: ServiceWorker | null) => next?.addEventListener("statechange", () => { if (next.state === "installed") announce(reg); });
    watch(reg.installing);
    reg.addEventListener("updatefound", () => watch(reg.installing));
  }).catch(() => undefined);   // no worker just means no offline shell; the app itself is unaffected

  return () => {
    stopped = true;
    sw.removeEventListener("controllerchange", onControllerChange);
    env.win.removeEventListener("online", check);
    env.doc.removeEventListener("visibilitychange", onVisible);
  };
}

/** `apply` is non-null while a newer build is waiting. */
export function useShellUpdate(): (() => void) | null {
  const [apply, setApply] = useState<(() => void) | null>(null);
  useEffect(() => startShellWorker((fn) => setApply(() => fn)), []);
  return apply;
}
