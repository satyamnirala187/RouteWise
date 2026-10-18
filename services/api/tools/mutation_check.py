"""Phase 1, 2A, 2B, 3A and 3B mutation check: inject known security/correctness defects into a scratch copy of
services/api and confirm the test suite fails for each.

Usage: python tools/mutation_check.py <scratch copy of services/api> <python with API deps> [name prefix]
With a prefix (e.g. "2B:", "3A:" or "3B:") only the matching targeted mutants run.
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
    "commit after response (scope=request)": (("deps.py", "routers/auth.py", "routers/admin.py", "routers/rider.py",
                                               "routers/admin_riders.py", "routers/admin_planning.py"),
                                              'Depends(get_db, scope="function")', "Depends(get_db)", "all"),
    "import parsing on event loop": ("routers/admin.py", "def upload_import(", "async def upload_import("),
    "DNS without timeout": ("netsafe.py", "        addrs = future.result(timeout=min(DNS_TIMEOUT_S, _remaining(deadline, clock)))", "        addrs = resolver(host)"),
    "raw URL control chars allowed": ("netsafe.py", "    if _UNSAFE_TARGET_CHARS.search(url):", "    if False:"),
    "malformed URL unhandled": ("locations.py", "    except ValueError:  # malformed authority", "    except KeyError:  # malformed authority"),
    "malformed redirect unhandled": ("locations.py", "        except ValueError:  # malformed Location header", "        except KeyError:  # malformed Location header"),
    # Phase 2A: rider setup, destinations, confirmation and readiness
    "stale confirmation accepted": ("routers/rider.py", "    if body.config_version != rr.config_version:", "    if False:"),
    "config change keeps confirmation": ("riders.py", "    rr.config_version += 1\n", ""),
    "depot move keeps confirmations": ("routers/admin_riders.py", "    if moved:", "    if False:"),
    "any old confirmation counts": ("riders.py", "    return rr.confirmed_version is not None and rr.confirmed_version == rr.config_version",
                                    "    return rr.confirmed_version is not None"),
    "admin view leaks destination coordinates": ("riders.py", '"destination": {"kind": endpoint.kind} if endpoint else None,',
                                                 '"destination": {"kind": endpoint.kind, "lat": endpoint.lat, "lng": endpoint.lng} if endpoint else None,'),
    "confirm skips depot locks": ("routers/rider.py", "    depots = lock_depots_shared(db)\n    rnd, rr = _locked_own(db, current, round_id)\n    if body.config_version",
                                  "    depots = {d.kind: d for d in db.scalars(select(Depot)).all()}\n    rnd, rr = _locked_own(db, current, round_id)\n    if body.config_version"),
    "round row lock skipped": ("riders.py", "    return db.get(DeliveryRound, round_id, with_for_update=True, populate_existing=True)",
                               "    return db.get(DeliveryRound, round_id, populate_existing=True)"),
    "rider lists others' rounds": ("routers/rider.py", ".where(RoundRider.rider_id == current.rider.id, RoundRider.participating.is_(True))",
                                   ".where(RoundRider.participating.is_(True))"),
    "removed rider still reaches round": ("routers/rider.py", "    if rr is None or not rr.participating:\n        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)\n    return rnd, rr",
                                          "    if rr is None:\n        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)\n    return rnd, rr"),
    "deactivated account ignored": ("riders.py", "    if not account_active:", "    if False:"),
    "unconfirmed riders not blocked": ("riders.py", '        elif rr.confirmed_version is None:\n            blockers.append(',
                                       '        elif False:\n            blockers.append('),
    "Last stop accepts a location": ("routers/rider.py", "        if body.lat is not None or body.lng is not None:", "        if False:"),
    "Home outside service area": ("routers/rider.py", "        if not settings.service_area.contains(loc.lat, loc.lng):", "        if False:"),
    "depot outside service area": ("routers/admin_riders.py", "    if not settings.service_area.contains(loc.lat, loc.lng):", "    if False:"),
    "capacity zero allowed": ("routers/admin_riders.py", "Field(ge=1, le=MAX_CAPACITY)", "Field(ge=0, le=MAX_CAPACITY)"),
    "inactive account added": ("routers/admin_riders.py", "        if participating and not user.active:", "        if False:"),
    "customer text is planning input": ("routers/admin.py", "    return order.location_state, order.lat, order.lng, order.status",
                                        "    return order.location_state, order.lat, order.lng, order.status, order.customer_name"),
    "pin edit not planning input": ("routers/admin.py", "    if _planning_fields(order) != before:\n        bump_round_input(db, order.round_id)",
                                    "    if _planning_fields(order) != before:\n        pass"),
    # Phase 2B, targeted at specific risks (run with the "2B:" prefix)
    "2B: order edits lock FOR UPDATE (deadlocks with plan commits)": (
        "routers/admin.py", 'order = db.get(Order, order_id, with_for_update={"key_share": True})',
        "order = db.get(Order, order_id, with_for_update=True)"),
    "2B: stale result committed": ("planning.py", "    if rnd.input_version != run.input_version or fingerprint(fresh, secret) != run.input_fingerprint:",
                                   "    if False:"),
    "2B: fingerprint not compared": ("planning.py", " or fingerprint(fresh, secret) != run.input_fingerprint:", ":"),
    "2B: commit without the round lock": ("planning.py", "    rnd = lock_round(db, snap.round_id)\n    run = db.get(PlanningRun",
                                          "    rnd = db.get(DeliveryRound, snap.round_id)\n    run = db.get(PlanningRun"),
    "2B: missing road priced zero": ("routing/planner.py", "                    cost[a][b] = FORBIDDEN if c is None else c",
                                     "                    cost[a][b] = 0 if c is None else c"),
    "2B: bike routed as scooter": ("planning.py", 'DOMAIN_PROFILE = {Vehicle.SCOOTER: "motor_scooter", Vehicle.BIKE: "motorcycle"}',
                                   'DOMAIN_PROFILE = {Vehicle.SCOOTER: "motor_scooter", Vehicle.BIKE: "motor_scooter"}'),
    "2B: Postponed orders re-planned": ("planning.py", '        if o.status == "Pending":\n            pending.append(o)',
                                        '        if o.status in ("Pending", "Postponed"):\n            pending.append(o)'),
    "2B: held orders ignored in capacity": ("planning.py", "capacity=r.capacity - held_count.get(r.rider_id, 0),",
                                            "capacity=r.capacity,"),
    "2B: synthetic matrix accepted": ("planning.py", '    if not plan.provenance.get("real_road"):', "    if False:"),
    "2B: unfinished runs not recovered": ("planning.py", "update(PlanningRun).where(PlanningRun.state.in_(ACTIVE_RUN_STATES))",
                                          "update(PlanningRun).where(PlanningRun.state.in_(()))"),
    # 2B correction pass: account deactivation and the commit-point lock
    "2B: deactivation does not bump rounds": ("accounts.py", "            for round_id in invalidated:\n                bump_round_input(db, round_id)",
                                              "            for round_id in invalidated:\n                pass"),
    "2B: deactivation skips the participation recheck": ("accounts.py", "        if not now_rounds <= rounds:", "        if False:"),
    "2B: capture without the account lock": ("planning.py", "        .with_for_update(read=True, of=User)\n", ""),
    # Phase 3A: the rider's read-only delivery view (run with the "3A:" prefix)
    "3A: deliveries ignore ownership": ("routers/rider.py", ".where(Assignment.rider_id == me, Order.round_id == round_id)",
                                        ".where(Order.round_id == round_id)"),
    "3A: another rider's round reachable": ("routers/rider.py", "    if rnd is None or not (joined or orders):", "    if rnd is None:"),
    "3A: superseded plan used": ("routers/rider.py", "select(RoutePlan).where(RoutePlan.round_id == round_id, RoutePlan.is_current.is_(True)))",
                                 "select(RoutePlan).where(RoutePlan.round_id == round_id).order_by(RoutePlan.version))"),
    "3A: other riders' plan rows sequenced": ("routers/rider.py", "PlanOrder.plan_id == plan.id, PlanOrder.rider_id == me,",
                                              "PlanOrder.plan_id == plan.id,"),
    "3A: unusable location navigable": ("routers/rider.py", " and o.lng is not None and area.contains(o.lat, o.lng)", " and o.lng is not None"),
    "3A: out-of-date plan not reported": ("routers/rider.py", '"out_of_date": plan.input_version != rnd.input_version, "superseded_versions"',
                                          '"out_of_date": False, "superseded_versions"'),
    "3A: Postponed kept in the route": ("routers/rider.py", '        if o.status == "Postponed":\n            postponed.append(item)',
                                        '        if False:\n            postponed.append(item)'),
    "3A: private destination coordinates in the view": (
        "routers/rider.py", '"destination": _place(endpoint.kind if endpoint else None, depots),',
        '"destination": {"kind": endpoint.kind, "lat": endpoint.lat, "lng": endpoint.lng} if endpoint else None,'),
    # Phase 3B: rider status updates and route validity (run with the "3B:" prefix)
    "3B: rider reopens Completed": ("routers/rider.py", 'RIDER_TRANSITIONS = {("Pending", "Completed"),',
                                    'RIDER_TRANSITIONS = {("Completed", "Pending"), ("Pending", "Completed"),'),
    "3B: ownership not re-checked under the round lock": ("routers/rider.py", "    if owner != me:\n        raise _status_conflict(",
                                                          "    if False:\n        raise _status_conflict("),
    "3B: round lock not taken before the re-check": ("routers/rider.py", "    rnd = lock_round(db, order.round_id)\n    owner =",
                                                     "    rnd = db.get(DeliveryRound, order.round_id)\n    owner ="),
    "3B: stale version accepted": ("routers/rider.py", "    if order.version != body.expected_version:", "    if False:"),
    "3B: repeated request applied twice": ("routers/rider.py", "    if order.status == body.status:\n        return {\"changed\": False,",
                                           "    if False:\n        return {\"changed\": False,"),
    "3B: order row not locked": ("routers/rider.py", "    order = db.get(Order, order_id, **order_lock_options())",
                                 "    order = db.get(Order, order_id)"),
    "3B: progress invalidates every saved route": ("routers/rider.py", "    bump_round_input(db, rnd.id, route=False)",
                                                   "    bump_round_input(db, rnd.id)"),
    "3B: admin status edits stop invalidating": ("routers/admin.py", "    if _planning_fields(order) != before:\n        bump_round_input(db, order.round_id)",
                                                 "    if _planning_fields(order) != before:\n        bump_round_input(db, order.round_id, route=order.status == before[3])"),
    "3B: out of date judged on the input revision": ("planning.py", "    out_of_date = plan.route_version != rnd.route_version",
                                                     "    out_of_date = plan.input_version != rnd.input_version"),
}
if len(sys.argv) > 3:
    MUTANTS = {k: v for k, v in MUTANTS.items() if k.startswith(sys.argv[3])}

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
