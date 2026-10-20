"""Phase 1, 2A, 2B, 3A, 3B, 4B and 4C mutation check: inject known security/correctness defects into a scratch copy of
services/api and confirm the test suite fails for each.

Usage: python tools/mutation_check.py <scratch copy of services/api> <python with API deps> [name prefix]
With a prefix (e.g. "2B:", "3A:", "3B:", "4B:" or "4C:") only the matching targeted mutants run.
MUTATION_TESTS (optional, space-separated test paths) limits each run to those tests.
Never run against the working tree: it rewrites source files in the given copy.
The copy must have the same .env access as the real tree (tests use TEST_DATABASE_URL).
"""

import os
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
    # Phase 4B: rider route revisions (run with the "4B:" prefix; MUTATION_TESTS may select test files)
    "4B: revision ignored by the delivery view": ("rider_routes.py", "    revision = current_revision(db, plan.id, rider_id)\n",
                                                  "    revision = None\n"),
    "4B: other riders' progress makes a reroute stale": ("reroute.py", '"plan": [t(snap.base_plan_id), snap.revision,',
                                                        '"plan": [snap.input_version, t(snap.base_plan_id), snap.revision,'),
    "4B: own status not part of the rider input": ("reroute.py", "        \"orders\": [[str(o.id), o.status, o.location_state,",
                                                   "        \"orders\": [[str(o.id), o.location_state,"),
    "4B: base plan not re-checked at commit": ("reroute.py", "    if fresh is None or fresh.base_plan_id != run.base_plan_id:",
                                               "    if fresh is None:"),
    "4B: destination change invalidates every rider": ("riders.py", "    bump_round_input(db, rr.round_id, route=False)\n",
                                                       "    bump_round_input(db, rr.round_id)\n"),
    "4B: confirmation invalidates every rider": ("routers/rider.py", "        bump_round_input(db, round_id, route=False)",
                                                 "        bump_round_input(db, round_id)"),
    "4B: inaccurate fix accepted": ("reroute.py", "    if req.accuracy_m > limits.gps_max_accuracy_m:", "    if False:"),
    "4B: old fix accepted": ("reroute.py", "    if req.age_s > limits.gps_max_age_s:", "    if False:"),
    "4B: position outside the service area accepted": ("reroute.py", "    if not settings.service_area.contains(req.lat, req.lng):",
                                                       "    if False:"),
    "4B: anyone's completion used as the last stop": ("reroute.py", "            and o.completed_by == snap.user_id and _usable(o, settings)]",
                                                      "            and _usable(o, settings)]"),
    "4B: configured start offered after a completion": ("reroute.py", "        if last is not None:\n            raise PlanningRefused(409, \"COMPLETED_STOP_AVAILABLE\"",
                                                        "        if False:\n            raise PlanningRefused(409, \"COMPLETED_STOP_AVAILABLE\""),
    "4B: reroute allowed while the admin replans": ("reroute.py", "    if active_round_run:\n", "    if False:\n"),
    "4B: completion time not recorded": ("orders.py", "        order.completed_at, order.completed_by = now, user_id",
                                         "        order.completed_at, order.completed_by = None, None"),
    "4B: admin plan leaves rider revisions current": ("planning.py", ".values(is_current=False, superseded_at=now).returning(RouteRevision.rider_id)",
                                                      ".where(False).values(is_current=False, superseded_at=now).returning(RouteRevision.rider_id)"),
    "4B: Postponed orders re-sequenced": ("reroute.py", '        return [o for o in self.orders if o.status == "Pending"]',
                                          '        return [o for o in self.orders if o.status != "Completed"]'),
    "4B: wrong vehicle profile": ("reroute.py", "profile=VEHICLE_PROFILE[prepared.inp.vehicle.value],", 'profile="motor_scooter",'),
    "4B: priority dropped on reroute": ("reroute.py", "                               first_priority=o.first_priority) for o in pending)",
                                       "                               first_priority=False) for o in pending)"),
    "4B: another rider can read a reroute run": ("routers/rider.py", 'if run is None or run.scope != "rider" or run.rider_id != current.rider.id:',
                                                 'if run is None or run.scope != "rider":'),
    # Phase 4C: same-building stop groups (run with the "4C:" prefix; MUTATION_TESTS may select test files)
    "4C: nearby pins count as the same pin": ("stop_groups.py", "        return (o.lat, o.lng)\n", "        return (round(o.lat, 3), round(o.lng, 3))\n"),
    "4C: group accepted without identical pins": ("stop_groups.py", "    if len({pin_of(o) for o in listed}) != 1:", "    if False:"),
    "4C: cross-round group accepted": ("stop_groups.py", "    if len(rounds) != len(ids) or any(r != round_id for r in rounds.values()):",
                                       "    if len(rounds) != len(ids):"),
    "4C: stale versions ignored when grouping": ("stop_groups.py", "    if stale:\n        raise GroupRefused(409, \"STALE_ORDERS\", \"These orders changed since you opened them; reload and try again.\", stale)",
                                                 "    if False:\n        raise GroupRefused(409, \"STALE_ORDERS\", \"These orders changed since you opened them; reload and try again.\", stale)"),
    "4C: invalid location accepted": ("stop_groups.py", "    if bad:\n        raise GroupRefused(422, \"LOCATION_NOT_VALID\"", "    if False:\n        raise GroupRefused(422, \"LOCATION_NOT_VALID\""),
    "4C: group id not fresh": ("stop_groups.py", "    building_id = uuid.uuid4().hex\n    for o in listed:", "    building_id = \"fixedgroupid0001\"\n    for o in listed:"),
    "4C: group request does not bump planning input": ("stop_groups.py", "    bump_round_input(db, round_id)\n    db.flush()\n    return True, listed",
                                                       "    db.flush()\n    return True, listed"),
    "4C: a changed pin keeps the order in its group": ("stop_groups.py", "    if order.building_id is None or pin_of(order) == before:\n        return None",
                                                       "    return None"),
    "4C: an unchanged pin leaves the group": ("stop_groups.py", "    if order.building_id is None or pin_of(order) == before:", "    if order.building_id is None:"),
    "4C: a group of one survives ungrouping": ("stop_groups.py", "    if len(rest) == 1:  # a group of one is not a group", "    if False:"),
    "4C: a group of one survives a pin change": ("stop_groups.py", "    if len(rest) == 1:\n        rest[0].building_id, rest[0].version, rest[0].updated_at = None, rest[0].version + 1, now\n        freed = [rest[0].order_code]",
                                                 "    if False:\n        rest[0].building_id, rest[0].version, rest[0].updated_at = None, rest[0].version + 1, now\n        freed = [rest[0].order_code]"),
    "4C: a pin edit does not lock its group": ("stop_groups.py", "    return lock_orders(db, {order_id} | (member_ids(db, round_id, building_id) if building_id else set()))",
                                               "    return lock_orders(db, {order_id})"),
    "4C: stale ungroup accepted": ("stop_groups.py", "    if order.version != version:\n        raise GroupRefused(409, \"STALE_ORDERS\", \"This order changed since you opened it; reload and try again.\",\n                           [order.order_code])",
                                   "    if False:\n        raise GroupRefused(409, \"STALE_ORDERS\", \"This order changed since you opened it; reload and try again.\",\n                           [order.order_code])"),
    "4C: group order rows not locked": ("stop_groups.py", "                      .with_for_update(key_share=True).execution_options(populate_existing=True)).all()",
                                        "                      .execution_options(populate_existing=True)).all()"),
    "4C: admin planning ignores groups": ("planning.py", "location_id=loc(o.lat, o.lng), building_id=o.building_id,", "location_id=loc(o.lat, o.lng),"),
    "4C: reroute ignores groups": ("reroute.py", "location_id=loc(o.lat, o.lng), building_id=o.building_id,", "location_id=loc(o.lat, o.lng),"),
    "4C: group left out of the reroute fingerprint": ("reroute.py", "t(o.completed_at), t(o.completed_by), o.building_id] for o in snap.orders],",
                                                      "t(o.completed_at), t(o.completed_by)] for o in snap.orders],"),
    "4C: group left out of the plan fingerprint": ("planning.py", "str(o.owner_rider_id) if o.owner_rider_id else None, o.building_id] for o in snap.orders],",
                                                   "str(o.owner_rider_id) if o.owner_rider_id else None] for o in snap.orders],"),
    "4C: same-pin badges ignore the service area": ("stop_groups.py", '        if suggestable(o, area):\n            by_pin.setdefault(pin_of(o), []).append(o)\n    out: dict[uuid.UUID, dict] = {}\n    for o in orders:\n        group = None\n        if o.building_id:\n            members = sorted(m.order_code for m in by_group[o.building_id])\n            group = {"id": o.building_id, "size": len(members), "members": members}\n        same = (sorted(m.order_code for m in by_pin[pin_of(o)] if m.id != o.id) if suggestable(o, area) else [])', '        if (pin_of(o) is not None and o.status != "Completed"):\n            by_pin.setdefault(pin_of(o), []).append(o)\n    out: dict[uuid.UUID, dict] = {}\n    for o in orders:\n        group = None\n        if o.building_id:\n            members = sorted(m.order_code for m in by_group[o.building_id])\n            group = {"id": o.building_id, "size": len(members), "members": members}\n        same = (sorted(m.order_code for m in by_pin[pin_of(o)] if m.id != o.id) if (pin_of(o) is not None and o.status != "Completed") else [])'),
    "4C: group membership hidden for an invalid pin": ("stop_groups.py", "        if o.building_id:\n            members = sorted(m.order_code for m in by_group[o.building_id])",
                                                       "        if o.building_id and valid_pin(o, area):\n            members = sorted(m.order_code for m in by_group[o.building_id])"),
    "4C: identical pins grouped without confirmation": ("routing/planner.py", "key = (\"b\", o.building_id, o.location_id, o.locked_rider_id) if o.building_id else (\"o\", o.id)",
                                                        "key = (\"b\", o.location_id, o.locked_rider_id)"),
    "4C: owner locks ignored when grouping": ("routing/planner.py", "key = (\"b\", o.building_id, o.location_id, o.locked_rider_id) if o.building_id else (\"o\", o.id)",
                                              "key = (\"b\", o.building_id, o.location_id) if o.building_id else (\"o\", o.id)"),
    "4C: a group counts as one capacity unit": ("routing/planner.py", "        return len(self.order_ids)\n", "        return 1\n"),
    "4C: priority customers not listed first": ("routing/planner.py", "        orders = sorted(orders, key=lambda o: not o.first_priority)  # stable: priority customers first",
                                                "        orders = list(orders)"),
    "4C: second stop at one building kept": ("routing/planner.py", "        if key is not None and key in at:", "        if False:"),
    "4C: rider view ignores priority inside a stop": ("routers/rider.py", "    items = sorted(items, key=lambda i: (not orders_by_id[i[\"id\"]].first_priority, i[\"order_code\"]))",
                                                      "    items = sorted(items, key=lambda i: (False, i[\"order_code\"]))"),
    "4C: admin plan ignores priority inside a stop": ("routers/admin_planning.py", "    in_stop = lambda oid, code: (oid not in first, code)  # noqa: E731",
                                                      "    in_stop = lambda oid, code: (False, code)  # noqa: E731"),
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
    r = subprocess.run([py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *os.environ.get("MUTATION_TESTS", "").split()],
                       cwd=root, capture_output=True, text=True)
    for path, orig in originals.items():
        path.write_text(orig)
    status = "KILLED" if r.returncode else "SURVIVED"
    killed += r.returncode != 0
    print(f"{status}: {name}", flush=True)
print(f"{killed}/{len(MUTANTS)} killed")
