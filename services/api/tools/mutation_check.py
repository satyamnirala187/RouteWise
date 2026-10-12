"""Phase 1 mutation check: inject known security/correctness defects into a scratch copy of
services/api and confirm the test suite fails for each.

Usage: python tools/mutation_check.py <scratch copy of services/api> <python with API deps>
Never run against the working tree: it rewrites source files in the given copy.
The copy must have the same .env access as the real tree (tests use TEST_DATABASE_URL).
"""

import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
py = sys.argv[2]
P = root / "routewise_api"
MUTANTS = {
    "csrf check skipped": ("deps.py", 'if not constant_time_equal(request.headers.get("x-csrf-token"), sess.csrf_token):', "if False:"),
    "origin check skipped": ("deps.py", "    if origin is not None and origin not in settings.allowed_origins:", "    if False:"),
    "riders allowed on admin": ("deps.py", '    if current.role != "admin":', '    if current.role not in ("admin", "rider"):'),
    "idle expiry ignored": ("deps.py", "        or now - sess.last_seen_at > settings.session_idle\n", ""),
    "absolute expiry ignored": ("deps.py", "        or now - sess.created_at > settings.session_absolute\n", ""),
    "logout does not revoke": ("routers/auth.py", "    current.session.revoked_at = now\n", ""),
    "login throttling off": ("routers/auth.py", "    if by_user >= MAX_FAILURES_PER_USERNAME or by_ip >= MAX_FAILURES_PER_IP:", "    if False:"),
    "rider sees all orders": ("routers/rider.py", ".where(Assignment.rider_id == current.rider.id)", ""),
    "private IPs allowed": ("netsafe.py", "    if not all(is_public_ip(a) for a in addrs):", "    if False:"),
    "connect by hostname": ("netsafe.py", "        sock = connector(ip, host, min(", "        sock = connector(host, host, min("),
    "TLS hostname check off": ("netsafe.py", "    ctx.minimum_version = ssl.TLSVersion.TLSv1_2\n", "    ctx.minimum_version = ssl.TLSVersion.TLSv1_2\n    ctx.check_hostname = False\n"),
    "redirect host not revalidated": ("locations.py", "            continue  # validated again", "            return LocationResult('resolved', 1.0, 1.0, 'short_link')  # validated again"),
    "camera centre accepted": ("locations.py", '        return _needs("map view centre only, not a destination pin; choose a pin manually")',
                               '        m = _CAMERA.search(path); return coordinates(m.group(1), m.group(2), "place_pin")'),
    "formula accepted": ("importer.py", '                if cell is not None and getattr(cell, "data_type", None) == "f":', "                if False:"),
    "numeric contact not warned": ("importer.py", "        if re.fullmatch(r\"0+\", fmt) and len(fmt) > len(digits):", "        return digits\n        if False:"),
    "zip ratio check off": ("importer.py", "                if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:", "                if False:"),
    "readiness ignores service area": ("orders.py", "        elif not area.contains(o.lat, o.lng):", "        elif False:"),
    "validation echoes input": ("main.py", '        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]', "        errors = exc.errors()"),
    # Correction pass (independent review findings)
    "import row lock removed": ("routers/admin.py", "with_for_update=True, populate_existing=True", "populate_existing=True"),
    "commit after response (scope=request)": (("deps.py", "routers/auth.py", "routers/admin.py", "routers/rider.py"),
                                              'Depends(get_db, scope="function")', "Depends(get_db)", "all"),
    "import parsing on event loop": ("routers/admin.py", "def upload_import(", "async def upload_import("),
    "DNS without timeout": ("netsafe.py", "        addrs = future.result(timeout=min(DNS_TIMEOUT_S, _remaining(deadline, clock)))", "        addrs = resolver(host)"),
    "raw URL control chars allowed": ("netsafe.py", "    if _UNSAFE_TARGET_CHARS.search(url):", "    if False:"),
    "malformed URL unhandled": ("locations.py", "    except ValueError:  # malformed authority", "    except KeyError:  # malformed authority"),
    "malformed redirect unhandled": ("locations.py", "        except ValueError:  # malformed Location header", "        except KeyError:  # malformed Location header"),
}

killed = 0
for name, (files, old, new, *mode) in MUTANTS.items():
    paths = [P / f for f in ((files,) if isinstance(files, str) else files)]
    originals = {path: path.read_text() for path in paths}
    for path, orig in originals.items():
        assert old in orig, f"mutant target missing: {name} in {path.name}"
        path.write_text(orig.replace(old, new) if mode == ["all"] else orig.replace(old, new, 1))
    r = subprocess.run([py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"], cwd=root, capture_output=True, text=True)
    for path, orig in originals.items():
        path.write_text(orig)
    status = "KILLED" if r.returncode else "SURVIVED"
    killed += r.returncode != 0
    print(f"{status}: {name}", flush=True)
print(f"{killed}/{len(MUTANTS)} killed")
