"""Step 2C, 3A, 3B and 4A targeted defect checks for the web app: inject one known defect at a time into
a scratch copy of apps/web and confirm the named tests fail (browser tests filtered by title, or
the vitest unit tests when the filter is "vitest"). Not an exhaustive run.

    python3 scripts/web_defect_check.py <empty scratch dir> [name prefix]

The copy gets its own apps/web (node_modules symlinked); services/api, scripts and .local are
symlinked read-only from this repository. Never run against the working tree.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# name: (file under apps/web, old, new, playwright -g filter); old/new may be tuples to change
# several places in that file at once.
MUTANTS = {
    "polling not stopped on navigation/round switch": (
        "src/pages/PlanPage.tsx", "    }).catch(handle);\n    return () => ac.abort();\n  }, [activeRunId, roundId, loadPlans, handle]);",
        "    }).catch(handle);\n    return () => undefined;\n  }, [activeRunId, roundId, loadPlans, handle]);", "polling stops"),
    "poll errors (session expiry) ignored": (
        "src/planning.ts", "      if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404)) throw e;",
        "      if (e instanceof ApiError && e.status === 401) continue;", "polling stops"),
    "stale round responses accepted": (
        "src/pages/PlanPage.tsx",
        ("    if (current.current !== id) return;  // e.g. a mode save", "    if (signal?.aborted || current.current !== id || seq !== loadSeq.current) return;"),
        ("    if (false) return;  // e.g. a mode save", "    if (signal?.aborted) return;"),
        "polling stops|mode changes"),
    "Optimize enabled before readiness": (
        "src/pages/PlanPage.tsx", "  const canOptimize = !!r && reasons.length === 0 && !busy;", "  const canOptimize = !!r && !busy;", "full round"),
    "plan not reloaded after a run ends": (
        "src/pages/PlanPage.tsx", "      if (res.kind === \"done\") await loadPlans(id);", "      if (res.kind === \"done\") await loadPlans(id, ac.signal);",
        "destination change during a solve"),
    "rejected run presented as the current result": (
        "src/pages/PlanPage.tsx", ': failed ? "Current plan (the latest run did not replace it)" : "Current plan"', ': "Current plan"',
        "destination change during a solve"),
    "saving a destination also confirms": (
        "src/components/DestinationCard.tsx", "      adopt(s);\n      setNote(s.confirmation.state === \"confirmed\"",
        "      adopt(await api<RiderSetup>(`/api/rider/rounds/${roundId}/confirm`, { method: \"POST\", json: { config_version: s.config_version } }));\n      setNote(s.confirmation.state === \"confirmed\"",
        "full round"),
    "version conflict silently reloaded over": (
        "src/pages/RoundSetupPage.tsx", "      setConflict(err instanceof ApiError && err.status === 409);\n      setNote({ kind: \"error\", text: err instanceof ApiError ? err.message : \"Save failed.\" });\n    } finally {\n      setBusy(false);\n    }\n  }\n\n  function save",
        "      setConflict(false); onReload();\n    } finally {\n      setBusy(false);\n    }\n  }\n\n  function save", "configuration change after planning"),
    "owner lock shown as assignment": (
        "src/pages/OrdersPage.tsx", "      {p.assigned_rider_id && (", "      {(p.assigned_rider_id || p.locked_rider_id) && (", "equal and manual"),
    # Step 3A: the rider's delivery view (e2e/phase3.spec.ts and src/links.test.ts).
    "3A: dial link from an unvalidated contact": (
        "src/links.ts", '  if (!CONTACT_CHARS.test(s) || s.lastIndexOf("+") > 0) {', "  if (false) {", "vitest"),
    "3A: dial link for too few digits": (
        "src/links.ts", "  if (digits.length < 7 || digits.length > 15 || /^0+$/.test(digits)) {", "  if (!digits) {", "safe call and navigation"),
    "3A: navigation link without a usable location": (
        "src/links.ts", "  if (!location) return { href: null, issue: fallback };",
        '  if (!location) return { href: "https://www.google.com/maps/", issue: null };', "unusable locations"),
    "3A: out-of-date warning hidden": (
        "src/components/DeliveryView.tsx", "            {plan.out_of_date && (", "            {false && (", "unusable locations"),
    "3A: saved order presented as a fresh route": (
        "src/components/DeliveryView.tsx", 'title={plan?.out_of_date ? "Pending deliveries — saved order (out of date)" : "Pending deliveries in route order"}',
        'title="Pending deliveries in route order"', "unusable locations"),
    "3A: Completed orders get call and navigation": (
        "src/components/DeliveryView.tsx", "      {!done && (", "      {true && (", "unusable locations"),
    "3A: late response for another round shown": (
        "src/pages/RiderPage.tsx",
        ("    viewAc.current?.abort();\n    const ac", "if (!ac.signal.aborted && current.current === id) { setView(v)",
         "    return () => { viewAc.current?.abort(); viewAc.current = null; };", "{view && view.round_id === roundId ?"),
        ("    const ac", "if (true) { setView(v)", "    return () => { viewAc.current = null; };", "{view ?"),
        "switching rounds"),
    # Step 3B: status updates (e2e/phase3b.spec.ts).
    "3B: status buttons enabled during a save": (
        "src/components/DeliveryView.tsx", "  const busy = actions.saving !== null;", "  const busy = false;", "in flight"),
    "3B: success shown before the server confirms": (
        "src/pages/RiderPage.tsx", "    setSaving({ id: item.id, target }); setNote(null); setFailed(null);",
        "    setSaving({ id: item.id, target }); setNote({ kind: \"ok\", text: `${item.order_code} saved as ${target}.` }); setFailed(null);",
        "in flight"),
    "3B: unconfirmed save reported as saved": (
        "src/pages/RiderPage.tsx", "        setFailed({ item, target, message:",
        "        setNote({ kind: \"ok\", text: `${item.order_code} saved as ${target}.` }); void ({ item, target, message:", "unconfirmed save"),
    "3B: conflict not reloaded": (
        "src/pages/RiderPage.tsx", "        setNote({ kind: e.status === 409 ? \"warn\" : \"error\", text: e.message });\n        loadView(id);",
        "        setNote({ kind: e.status === 409 ? \"warn\" : \"error\", text: e.message });", "conflicting change"),
    "3B: late status answer applied to another round": (
        "src/pages/RiderPage.tsx", "      if (current.current !== id || res.view.round_id !== id) return;  // the rider moved to another round\n", "",
        "late status answer"),
    "3B: delivered without the second tap": (
        "src/components/DeliveryView.tsx", '(t.target === "Completed" ? actions.confirm(item.id) : actions.change(item, t.target))',
        "actions.change(item, t.target)", "postpones, returns"),
    # Step 4A: the next-customer panel (e2e/phase4a.spec.ts and src/next.test.ts).
    "4A: tapping Call records a status": (
        "src/components/DeliveryView.tsx", 'data-testid="next-call"',
        'data-testid="next-call" onClick={() => actions?.change(item, "Postponed")}', "tapping Call changes nothing"),
    "4A: panel advances before the server confirms": (
        "src/pages/RiderPage.tsx", "    setSaving({ id: item.id, target }); setNote(null); setFailed(null);",
        "    setSaving({ id: item.id, target }); setNote(null); setFailed(null);\n"
        "    setView((v) => v && { ...v, sequence: v.sequence.filter((st) => !st.orders.some((o) => o.id === item.id)) });",
        "moves on only after"),
    "4A: Customer unavailable enabled during a save": (
        "src/components/DeliveryView.tsx", "disabled={busy} aria-busy={mine} aria-label={`Customer unavailable",
        "disabled={false} aria-busy={mine} aria-label={`Customer unavailable", "moves on only after"),
    "4A: Postponed or Completed order picked as next": (
        "src/next.ts", '    const pending = stop.orders.filter((o) => o.status === "Pending");', "    const pending = stop.orders;", "vitest"),
    "4A: order outside the saved route picked as next": (
        "src/next.ts", '  if (unsequenced > 0) return { kind: "unsequenced", count: unsequenced, planned: !!view.plan };',
        '  if (unsequenced > 0) return { kind: "next", item: view.unsequenced[0], stop: 0, others: 0, stale: false };', "empty states"),
    "4A: out-of-date route shown as plain Next": (
        "src/components/DeliveryView.tsx", 'data-testid="next-customer-label">\n          {stale ? "Next in saved order" : "Next"}',
        'data-testid="next-customer-label">\n          {"Next"}', "uncertain save"),
    "4A: uncertain save hidden from the panel": (
        "src/components/DeliveryView.tsx", "      {failed && actions && (", "      {false && actions && (", "uncertain save"),
    "4A: undialable contact dialled anyway": (
        "src/components/DeliveryView.tsx", "  const call = telLink(item.contact);\n  const busy = !!actions?.saving;",
        "  const call = { href: `tel:${item.contact}`, issue: null };\n  const busy = !!actions?.saving;", "cannot be dialled"),
    # 2C correction pass: readiness refresh and serialized mode changes.
    "no Refresh readiness action": (
        "src/pages/PlanPage.tsx", "onClick={() => roundId && refresh(roundId)}", "onClick={() => undefined}", "readiness refresh"),
    "no refresh when the window regains focus": (
        "src/pages/PlanPage.tsx", '    window.addEventListener("focus", onFocus);\n', "", "readiness refresh"),
    "readiness polled while idle": (
        "src/pages/PlanPage.tsx", '    window.addEventListener("focus", onFocus);\n',
        '    window.addEventListener("focus", onFocus);\n    const idle = setInterval(onFocus, 1000);\n    void idle;\n', "readiness refresh"),
    "overlapping mode saves allowed": (
        "src/pages/PlanPage.tsx",
        ("<fieldset disabled={running || savingMode}", "if (!roundId || !readiness || roundId in modeSavesRef.current || readiness.mode === mode) return;"),
        ("<fieldset disabled={running}", "if (!roundId || !readiness || readiness.mode === mode) return;"),
        "mode changes"),
    "Optimize enabled during a mode save": (
        "src/pages/PlanPage.tsx", '  if (savingMode) reasons.push("the distribution mode is being saved");\n', "", "mode changes"),
    "pending mode save shared across rounds": (
        "src/pages/PlanPage.tsx", "const pendingMode = roundId ? modeSaves[roundId] : undefined;",
        "const pendingMode = Object.values(modeSaves)[0];", "mode changes"),
}


def main() -> int:
    scratch = Path(sys.argv[1]).resolve()
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    if scratch == ROOT or ROOT in scratch.parents:
        raise SystemExit("use a scratch directory outside the repository")
    web = scratch / "apps" / "web"
    if web.exists():
        shutil.rmtree(web)
    shutil.copytree(ROOT / "apps" / "web", web, ignore=shutil.ignore_patterns("node_modules", "dist", "test-results"))
    (web / "node_modules").symlink_to(ROOT / "apps" / "web" / "node_modules")
    for name in ("services", "scripts", ".local", "tests", "spikes"):
        link = scratch / name
        if not link.exists():
            link.symlink_to(ROOT / name)
    env = {**os.environ, "E2E_SHOTS_DIR": str(scratch / "shots1"), "E2E_2C_SHOTS_DIR": str(scratch / "shots2c"),
           "E2E_3A_SHOTS_DIR": str(scratch / "shots3a"), "E2E_3B_SHOTS_DIR": str(scratch / "shots3b"),
           "E2E_4A_SHOTS_DIR": str(scratch / "shots4a")}
    killed = total = 0
    for name, (rel, old, new, grep) in MUTANTS.items():
        if not name.startswith(only):
            continue
        total += 1
        path = web / rel
        orig = text = path.read_text()
        for o, n in zip(*((old, new) if isinstance(old, tuple) else ((old,), (new,)))):
            assert text.count(o) == 1, f"mutant target missing or ambiguous: {name}"
            text = text.replace(o, n, 1)
        path.write_text(text)
        # The same steps as scripts/e2e.sh, but Playwright runs from the mutated copy of apps/web.
        r = subprocess.run(["bash", "-c", f'cd "{web}" && "{ROOT}/scripts/dev-db.sh" start >/dev/null && '
                            f'"{ROOT}/scripts/dev-db.sh" create-db routewise_e2e >/dev/null && '
                            f'export E2E_STATE="$("{ROOT}/services/api/.venv/bin/python" "{ROOT}/services/api/scripts/e2e_setup.py")" && '
                            f'export E2E_DATABASE_URL="$(python3 -c \'import json,sys; print(json.load(open(sys.argv[1]))["database_url"])\' "$E2E_STATE")" && '
                            f'rm -f "{ROOT}/.local/e2e/hold-solve" && ' + (
                                "npx vitest run" if grep == "vitest" else
                                f'npx playwright test e2e/phase2.spec.ts e2e/phase3.spec.ts e2e/phase3b.spec.ts e2e/phase4a.spec.ts --project desktop -g "{grep}"')],
                           env=env, capture_output=True, text=True)
        path.write_text(orig)
        status = "KILLED" if r.returncode else "SURVIVED"
        killed += r.returncode != 0
        tail = [ln for ln in r.stdout.splitlines() if "passed" in ln or "failed" in ln or "Tests" in ln]
        print(f"{status}: {name}  [{' / '.join(tail[-2:])}]", flush=True)
    print(f"{killed}/{total} killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
