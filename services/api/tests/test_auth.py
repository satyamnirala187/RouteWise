"""Login, cookies, expiry (12 h idle / 7 days absolute), logout, throttling, hashing."""

from dataclasses import replace

from sqlalchemy import select, text

from routewise_api.models import Session, User

from .conftest import Browser, make_user


def test_login_sets_hardened_session_cookie_and_returns_role(app, browser):
    make_user(app, "admin1", "admin")
    b = browser()
    r = b.login("admin1")
    assert r.status_code == 200 and r.json() == {"ok": True, "role": "admin"}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("rw_session=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie and "Max-Age=604800" in cookie  # 7 days
    s = b.get("/api/auth/session").json()
    assert s["role"] == "admin" and s["username"] == "admin1" and len(s["csrf_token"]) >= 40


def test_production_cookie_is_secure_and_host_prefixed(app, settings, clock, db_url):
    from routewise_api.main import create_app

    prod = create_app(replace(settings, env="production", cookie_secure=True), clock=clock)
    make_user(prod, "admin1", "admin")
    b = Browser(prod, base_url="https://testserver")
    r = b.login("admin1")
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-rw_session=") and "Secure" in cookie and "HttpOnly" in cookie
    assert "Domain" not in cookie
    assert r.headers["strict-transport-security"].startswith("max-age=")
    assert b.get("/api/auth/session").status_code == 200
    assert b.get("/api/docs").status_code in (404, 200) and prod.openapi_url is None
    prod.state.engine.dispose()


def test_wrong_and_unknown_credentials_get_the_same_answer(app, browser):
    make_user(app, "admin1", "admin")
    b = browser()
    wrong = b.login("admin1", "not the password!!")
    unknown = b.login("nobody", "not the password!!")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Wrong username or password"}
    assert b.get("/api/auth/session").status_code == 401


def test_username_is_case_insensitive(app, browser):
    make_user(app, "admin1", "admin")
    assert browser().login("ADMIN1").status_code == 200


def test_passwords_are_argon2id_and_tokens_are_never_stored(app, browser, db):
    make_user(app, "admin1", "admin")
    b = browser()
    b.login("admin1")
    user = db.scalar(select(User).where(User.username == "admin1"))
    assert user.password_hash.startswith("$argon2id$") and "correct horse" not in user.password_hash
    raw = b.client.cookies.get("rw_session")
    stored = db.scalars(select(Session.token_hash)).all()
    assert raw not in stored and all(len(h) == 64 for h in stored)


def test_login_throttling_after_repeated_failures(app, browser):
    make_user(app, "admin1", "admin")
    b = browser()
    for _ in range(5):
        assert b.login("admin1", "wrong password!!").status_code == 401
    assert b.login("admin1").status_code == 429  # even the right password is refused while locked


def test_throttle_window_expires(app, browser, clock):
    make_user(app, "admin1", "admin")
    b = browser()
    for _ in range(5):
        b.login("admin1", "wrong password!!")
    clock.advance(minutes=16)
    assert b.login("admin1").status_code == 200


def test_login_requires_json_and_same_origin(app, browser):
    make_user(app, "admin1", "admin")
    b = browser()
    form = b.client.post("/api/auth/login", data={"username": "admin1", "password": "correct horse battery"},
                         headers={"Origin": "http://localhost:5173"})
    assert form.status_code in (415, 422)
    assert b.login("admin1", origin="https://evil.example").status_code == 403


def test_idle_expiry_after_12_hours(app, browser, clock):
    make_user(app, "admin1", "admin")
    b = browser()
    b.login("admin1")
    clock.advance(hours=11, minutes=59)
    assert b.get("/api/auth/session").status_code == 200  # activity refreshes the idle timer
    clock.advance(hours=11, minutes=59)
    assert b.get("/api/auth/session").status_code == 200
    clock.advance(hours=12, seconds=1)
    r = b.get("/api/auth/session")
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()
    clock.advance(seconds=1)
    assert b.get("/api/auth/session").status_code == 401  # revoked for good, not just stale


def test_absolute_expiry_after_7_days_despite_activity(app, browser, clock):
    make_user(app, "admin1", "admin")
    b = browser()
    b.login("admin1")
    for _ in range(14):  # active every 11 h for > 6 days
        clock.advance(hours=11)
        assert b.get("/api/auth/session").status_code == 200
    clock.advance(hours=11)  # 165 h > 168? not yet: 15 * 11 = 165 h
    assert b.get("/api/auth/session").status_code == 200
    clock.advance(hours=3, seconds=1)  # 168 h + 1 s
    assert b.get("/api/auth/session").status_code == 401


def test_logout_requires_csrf_and_revokes_server_side(app, browser):
    make_user(app, "admin1", "admin")
    b = browser()
    b.login("admin1")
    stolen = b.client.cookies.get("rw_session")
    assert b.send("POST", "/api/auth/logout", csrf=False).status_code == 403
    r = b.send("POST", "/api/auth/logout")
    assert r.status_code == 200 and 'rw_session=""' in r.headers["set-cookie"]
    replay = Browser(app)
    replay.client.cookies.set("rw_session", stolen)
    assert replay.get("/api/auth/session").status_code == 401  # a copied cookie is dead after logout


def test_deactivated_user_is_locked_out_immediately(app, browser, db):
    make_user(app, "admin1", "admin")
    b = browser()
    b.login("admin1")
    db.execute(text("UPDATE users SET active = false WHERE username = 'admin1'"))
    db.commit()
    assert b.get("/api/auth/session").status_code == 401
    assert browser().login("admin1").status_code == 401


def test_cli_creates_user_without_password_in_argv(app, settings, monkeypatch, capsys, db):
    import io

    from routewise_api import cli

    monkeypatch.setattr("routewise_api.cli.load_settings", lambda: settings)
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert cli.main(["create-user", "--username", "Rider9", "--role", "rider", "--name", "Rider Nine",
                     "--vehicle", "bike"]) == 0
    assert "created rider 'rider9'" in capsys.readouterr().out
    assert Browser(app).login("rider9", "a long enough password").status_code == 200
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    try:
        cli.main(["create-user", "--username", "x", "--role", "admin"])
        raise AssertionError("short password accepted")
    except ValueError:
        pass
