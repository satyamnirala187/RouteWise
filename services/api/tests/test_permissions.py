"""Server-side authorization on every endpoint, CSRF on every mutation, cross-rider isolation."""

import re
import uuid

import pytest
from sqlalchemy import select

from routewise_api.models import Assignment, DeliveryRound, Order, Rider, User

from .conftest import Browser, make_user

PUBLIC = {("GET", "/api/health"), ("POST", "/api/auth/login")}


def all_api_routes(app) -> list[tuple[str, str]]:
    spec = app.openapi()
    return sorted((m.upper(), p) for p, ops in spec["paths"].items() for m in ops if p.startswith("/api/"))


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_route_inventory_is_what_we_expect(app):
    routes = all_api_routes(app)
    assert len(routes) >= 14
    assert all(p.startswith(("/api/auth", "/api/admin", "/api/rider", "/api/health")) for _, p in routes)


def test_every_non_public_endpoint_rejects_anonymous_requests(app):
    anon = Browser(app)
    for method, path in all_api_routes(app):
        if (method, path) in PUBLIC:
            continue
        r = anon.send(method, concrete(path), csrf=False)
        assert r.status_code == 401, (method, path, r.status_code)


def test_riders_are_refused_on_every_admin_endpoint(app):
    make_user(app, "rider1", "rider")
    rb = Browser(app)
    rb.login("rider1")
    for method, path in all_api_routes(app):
        if path.startswith("/api/admin"):
            r = rb.send(method, concrete(path))
            assert r.status_code == 403, (method, path, r.status_code)


def test_admins_are_refused_on_rider_endpoints(app, admin):
    for method, path in all_api_routes(app):
        if path.startswith("/api/rider"):
            assert admin.send(method, concrete(path)).status_code == 403, (method, path)


def test_every_mutation_requires_the_sessions_csrf_token(app, admin, browser):
    make_user(app, "admin2", "admin")
    other = browser()
    other.login("admin2")
    mutations = [(m, p) for m, p in all_api_routes(app) if m in {"POST", "PUT", "PATCH", "DELETE"}
                 and (m, p) not in PUBLIC and p.startswith("/api/admin")]
    assert mutations
    for method, path in mutations:
        url = concrete(path)
        assert admin.send(method, url, csrf=False).status_code == 403, ("missing", method, path)
        assert admin.send(method, url, headers={"X-CSRF-Token": "x" * 43}, csrf=False).status_code == 403
        assert admin.send(method, url, headers={"X-CSRF-Token": other.csrf}, csrf=False).status_code == 403, \
            ("token of another session", method, path)
        assert admin.send(method, url, origin="https://evil.example").status_code == 403, ("origin", method, path)


@pytest.fixture
def two_riders_with_orders(app, db):
    a = make_user(app, "rider_a", "rider", rider_name="Rider A")
    b = make_user(app, "rider_b", "rider", rider_name="Rider B")
    owner = make_user(app, "admin_x", "admin")
    rnd = DeliveryRound(name="t", created_by=owner.id)
    db.add(rnd)
    db.flush()
    orders = {}
    for i, user in enumerate((a, b, a)):
        o = Order(order_code=f"RW-T{i}", round_id=rnd.id, source_row=i + 2, customer_name=f"Test Customer {i}",
                  product="Box", contact=f"0000000000{i}", location_link="geo:28.68,77.2",
                  location_state="resolved", lat=28.68, lng=77.2, location_source="geo_uri")
        db.add(o)
        db.flush()
        rider = db.scalar(select(Rider).where(Rider.user_id == user.id))
        db.add(Assignment(order_id=o.id, rider_id=rider.id))
        orders.setdefault(user.username, []).append(o)
    o = Order(order_code="RW-UNASSIGNED", round_id=rnd.id, source_row=9, customer_name="Test Customer U",
              product="Box", contact="000", location_link="geo:28.68,77.2", location_state="needs_correction")
    db.add(o)
    db.commit()
    orders["unassigned"] = [o]
    return orders


def test_rider_sees_only_own_orders_with_minimal_fields(app, two_riders_with_orders):
    ra = Browser(app)
    ra.login("rider_a")
    mine = ra.get("/api/rider/orders").json()
    assert sorted(o["order_code"] for o in mine) == ["RW-T0", "RW-T2"]
    assert set(mine[0]) == {"id", "order_code", "customer_name", "product", "contact", "instructions", "lat", "lng", "status"}


def test_rider_cannot_read_another_riders_or_unassigned_order(app, two_riders_with_orders):
    ra = Browser(app)
    ra.login("rider_a")
    b_order = two_riders_with_orders["rider_b"][0]
    unassigned = two_riders_with_orders["unassigned"][0]
    for o in (b_order, unassigned):
        r = ra.get(f"/api/rider/orders/{o.id}")
        assert r.status_code == 404 and "Test Customer" not in r.text
    assert ra.get(f"/api/rider/orders/{two_riders_with_orders['rider_a'][0].id}").status_code == 200
    rnd = b_order.round_id
    assert ra.get(f"/api/admin/rounds/{rnd}/orders").status_code == 403


def test_rider_b_sees_only_b(app, two_riders_with_orders):
    rb = Browser(app)
    rb.login("rider_b")
    assert [o["order_code"] for o in rb.get("/api/rider/orders").json()] == ["RW-T1"]


PHASE_2A_ROUTES = {
    ("GET", "/api/admin/depots"), ("PUT", "/api/admin/depots/{kind}"),
    ("GET", "/api/admin/riders"), ("PATCH", "/api/admin/riders/{rider_id}"),
    ("GET", "/api/admin/rounds/{round_id}/riders"), ("PUT", "/api/admin/rounds/{round_id}/riders/{rider_id}"),
    ("GET", "/api/rider/rounds"), ("GET", "/api/rider/rounds/{round_id}"),
    ("PUT", "/api/rider/rounds/{round_id}/destination"), ("POST", "/api/rider/rounds/{round_id}/confirm"),
}


def test_phase_2a_routes_exist_and_confirmation_is_rider_only(app):
    routes = set(all_api_routes(app))
    assert PHASE_2A_ROUTES <= routes
    writes_naming_rider_choices = {(m, p) for m, p in routes if m != "GET" and ("confirm" in p or "destination" in p)}
    assert writes_naming_rider_choices and all(p.startswith("/api/rider/") for _, p in writes_naming_rider_choices)


def test_every_rider_mutation_requires_the_sessions_csrf_token(app):
    make_user(app, "rider1", "rider")
    make_user(app, "rider2", "rider")
    rider, other = Browser(app), Browser(app)
    rider.login("rider1")
    other.login("rider2")
    mutations = [(m, p) for m, p in all_api_routes(app) if m in {"POST", "PUT", "PATCH", "DELETE"}
                 and p.startswith("/api/rider")]
    assert mutations
    for method, path in mutations:
        url = concrete(path)
        assert rider.send(method, url, csrf=False).status_code == 403, ("missing", method, path)
        assert rider.send(method, url, headers={"X-CSRF-Token": "x" * 43}, csrf=False).status_code == 403
        assert rider.send(method, url, headers={"X-CSRF-Token": other.csrf}, csrf=False).status_code == 403, \
            ("token of another session", method, path)
        assert rider.send(method, url, origin="https://evil.example").status_code == 403, ("origin", method, path)
