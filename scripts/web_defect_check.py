"""Step 2C targeted defect checks for the web app: inject one known defect at a time into a
scratch copy of apps/web and confirm the named browser tests fail. Not an exhaustive run.

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
    env = {**os.environ, "E2E_SHOTS_DIR": str(scratch / "shots1"), "E2E_2C_SHOTS_DIR": str(scratch / "shots2c")}
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
                            f'rm -f "{ROOT}/.local/e2e/hold-solve" && npx playwright test e2e/phase2.spec.ts --project desktop -g "{grep}"'],
                           env=env, capture_output=True, text=True)
        path.write_text(orig)
        status = "KILLED" if r.returncode else "SURVIVED"
        killed += r.returncode != 0
        tail = [ln for ln in r.stdout.splitlines() if "passed" in ln or "failed" in ln]
        print(f"{status}: {name}  [{' / '.join(tail[-2:])}]", flush=True)
    print(f"{killed}/{total} killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
