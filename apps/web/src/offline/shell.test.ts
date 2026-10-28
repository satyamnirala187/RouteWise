import { describe, expect, it, vi } from "vitest";
import { shellWorkerSupported, startShellWorker, type ShellEnv } from "./shell";

type Listener = () => void;
const emitter = () => {
  const map = new Map<string, Set<Listener>>();
  return {
    addEventListener: (t: string, fn: Listener) => { (map.get(t) ?? map.set(t, new Set()).get(t)!).add(fn); },
    removeEventListener: (t: string, fn: Listener) => { map.get(t)?.delete(fn); },
    emit: (t: string) => map.get(t)?.forEach((fn) => fn()),
    count: (t: string) => map.get(t)?.size ?? 0,
  };
};

function setup(over: { prod?: boolean; secure?: boolean; worker?: boolean; controller?: boolean; waiting?: boolean } = {}) {
  const { prod = true, secure = true, worker = true, controller = true, waiting = false } = over;
  const container = emitter();
  const registration = Object.assign(emitter(), {
    waiting: waiting ? { postMessage: vi.fn() } : null,
    installing: null as { state: string; addEventListener: Listener extends never ? never : (t: string, fn: Listener) => void } | null,
    update: vi.fn(async () => undefined),
  });
  const serviceWorker = Object.assign(container, {
    controller: controller ? {} : null,
    register: vi.fn(async () => registration),
  });
  const win = emitter();
  const doc = Object.assign(emitter(), { visibilityState: "visible" as DocumentVisibilityState });
  const reload = vi.fn();
  const env = { prod, win: Object.assign(win, { isSecureContext: secure }), doc, nav: worker ? { serviceWorker } : {}, reload } as unknown as ShellEnv;
  return { env, serviceWorker, registration, win, doc, reload };
}
const settle = () => new Promise((r) => setTimeout(r, 0));

describe("when the shell worker is used", () => {
  it.each([
    ["the Vite dev server (not a production build)", { prod: false }],
    ["an insecure context (plain HTTP on the network)", { secure: false }],
    ["a browser without service workers", { worker: false }],
  ])("never registers for %s", async (_name, over) => {
    const t = setup(over);
    expect(shellWorkerSupported(t.env)).toBe(false);
    const cleanup = startShellWorker(vi.fn(), t.env);
    await settle();
    expect(t.serviceWorker.register).not.toHaveBeenCalled();
    cleanup();
  });

  it("registers /sw.js at the root scope for a built app in a secure context", async () => {
    const t = setup();
    startShellWorker(vi.fn(), t.env);
    await settle();
    expect(t.serviceWorker.register).toHaveBeenCalledWith("/sw.js", { scope: "/" });
  });

  it("ignores a failed registration (the app works without the offline shell)", async () => {
    const t = setup();
    t.serviceWorker.register.mockRejectedValueOnce(new Error("blocked"));
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    expect(onReady).not.toHaveBeenCalled();
  });
});

describe("an update waiting behind the running worker", () => {
  it("is announced, and nothing is forced: no skip, no reload", async () => {
    const t = setup({ waiting: true });
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    expect(onReady).toHaveBeenCalledOnce();
    expect(t.registration.waiting!.postMessage).not.toHaveBeenCalled();
    expect(t.reload).not.toHaveBeenCalled();
  });

  it("takes over only after the rider chooses, and then reloads once the new worker is in charge", async () => {
    const t = setup({ waiting: true });
    let apply = () => undefined as void;
    startShellWorker((fn) => { apply = fn; }, t.env);
    await settle();
    apply();
    expect(t.registration.waiting!.postMessage).toHaveBeenCalledWith({ type: "SKIP_WAITING" });
    expect(t.reload).not.toHaveBeenCalled();   // not before the new worker controls the page
    t.serviceWorker.emit("controllerchange");
    expect(t.reload).toHaveBeenCalledOnce();
  });

  it("offers a reload, and does not reload by itself, when ANOTHER tab applied the update under this older page", async () => {
    const t = setup();   // this page started under the old worker
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    t.serviceWorker.emit("controllerchange");
    expect(t.reload).not.toHaveBeenCalled();
    expect(onReady).toHaveBeenCalledOnce();
    onReady.mock.calls[0][0]();   // the rider taps "Reload to update"
    expect(t.reload).toHaveBeenCalledOnce();
  });

  it("treats a page claimed by the first install as an older page for the NEXT update (another tab applies it)", async () => {
    const t = setup({ controller: false });   // this page was the very first visit
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    t.serviceWorker.emit("controllerchange");   // the first install claims the page: nothing to offer
    expect(onReady).not.toHaveBeenCalled();
    t.serviceWorker.emit("controllerchange");   // a newer build takes over: offer a reload, never force one
    expect(onReady).toHaveBeenCalledOnce();
    expect(t.reload).not.toHaveBeenCalled();
    onReady.mock.calls[0][0]();
    expect(t.reload).toHaveBeenCalledOnce();
  });

  it("does not reload or announce when the controller changes on a first visit (the first install claiming the page)", async () => {
    const t = setup({ controller: false });
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    t.serviceWorker.emit("controllerchange");
    expect(t.reload).not.toHaveBeenCalled();
    expect(onReady).not.toHaveBeenCalled();
  });

  it("is announced when a newer build finishes installing while this page is controlled", async () => {
    const t = setup();
    const next = Object.assign(emitter(), { state: "installing" });
    t.registration.installing = next as never;
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    t.registration.waiting = { postMessage: vi.fn() };
    t.registration.emit("updatefound");
    next.state = "installed";
    next.emit("statechange");
    expect(onReady).toHaveBeenCalledOnce();
  });

  it("is announced when a newer build was already installing when registration finished", async () => {
    const t = setup();
    const next = Object.assign(emitter(), { state: "installing" });
    t.registration.installing = next as never;
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    t.registration.waiting = { postMessage: vi.fn() };   // no `updatefound` will fire: it already did
    next.state = "installed";
    next.emit("statechange");
    expect(onReady).toHaveBeenCalledOnce();
  });

  it("is not an update when there was no worker before (the first install)", async () => {
    const t = setup({ controller: false, waiting: true });
    const onReady = vi.fn();
    startShellWorker(onReady, t.env);
    await settle();
    expect(onReady).not.toHaveBeenCalled();
  });
});

describe("looking for a new build", () => {
  it("checks when the page becomes visible or the connection returns, and ignores a failed check", async () => {
    const t = setup();
    startShellWorker(vi.fn(), t.env);
    await settle();
    t.doc.emit("visibilitychange");
    t.win.emit("online");
    expect(t.registration.update).toHaveBeenCalledTimes(2);
    t.registration.update.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    t.win.emit("online");   // offline: must not throw
    await settle();
    t.doc.visibilityState = "hidden";
    t.doc.emit("visibilitychange");
    expect(t.registration.update).toHaveBeenCalledTimes(3);   // hidden pages do not check
  });

  it("removes its listeners and stops announcing after cleanup", async () => {
    const t = setup({ waiting: true });
    const onReady = vi.fn();
    const cleanup = startShellWorker(onReady, t.env);
    cleanup();
    await settle();
    expect(onReady).not.toHaveBeenCalled();
    expect([t.serviceWorker.count("controllerchange"), t.win.count("online"), t.doc.count("visibilitychange")]).toEqual([0, 0, 0]);
  });
});
