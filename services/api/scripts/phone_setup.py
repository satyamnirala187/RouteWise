"""Phase 3 real-phone test data (local only). See docs/phase3/PHONE-TEST-GUIDE.md.

    services/api/.venv/bin/python services/api/scripts/phone_setup.py

Resets ONLY the dedicated database `routewise_phone` (refuses any other name), then builds one
planned round through the application's own API, in process:
  - two synthetic riders and one admin, with random passwords;
  - Office/Warehouse and 8 synthetic customers on public DU North Campus OpenStreetMap points
    (tests/fixtures/public_locations_du_north.json), imported through the real Excel import;
  - riders choose and confirm destinations; the round is planned on the LOCAL Valhalla tiles.

Optionally asks (hidden input) for one phone number the owner controls, for the Call check; it
is stored only in `routewise_phone` as the contact of Test Rider A's first stop and is never
printed or written to a file. Synthetic customers get non-dialable contacts (0000000001 …).

Writes, git-ignored and readable only by you:
  .local/phone/credentials.txt  usernames and passwords
  .local/phone/expected.txt     Rider A's stops with the public place and the expected Maps link
The development database (routewise_dev) and the test databases are never touched.
"""

from __future__ import annotations

import getpass
import io
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from routewise_api.config import REPO_ROOT, load_settings  # noqa: E402
from routewise_api.main import create_app  # noqa: E402
from routewise_api.models import Rider, User  # noqa: E402
from routewise_api.security import hash_password  # noqa: E402

DB_NAME = "routewise_phone"
OUT = REPO_ROOT / ".local" / "phone"
POINTS = ["kirori_mal", "hansraj", "hindu_college", "st_stephens", "miranda_house", "ramjas", "srcc", "daulat_ram"]
RIDERS = {  # username: (display name, vehicle, capacity, start, destination)
    "phone_rider_a": ("Test Rider A", "scooter", 4, "office", "last_stop"),
    "phone_rider_b": ("Test Rider B", "bike", 4, "warehouse", "office"),
}
CONTACT_CHARS = re.compile(r"^[0-9+\-() .]+$")


def phone_db_url() -> str:
    base = os.environ.get("DATABASE_URL", "")
    if not base:
        raise SystemExit("DATABASE_URL is not set (run scripts/dev-db.sh init)")
    url = base.rsplit("/", 1)[0] + "/" + DB_NAME
    if not url.endswith("/" + DB_NAME):
        raise SystemExit("refusing: not the routewise_phone database")
    return url


def reset_schema(url: str) -> None:
    eng = create_engine(url)
    with eng.begin() as conn:
        if conn.execute(text("SELECT current_database()")).scalar_one() != DB_NAME:
            raise SystemExit("refusing: connected to a database other than routewise_phone")
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    eng.dispose()
    cfg = Config(str(API / "alembic.ini"))
    cfg.set_main_option("script_location", str(API / "migrations"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={url}"]})()
    command.upgrade(cfg, "head")


def workbook(points: dict) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Product", "Contact", "Location", "Delivery Instructions"])
    for i, place in enumerate(POINTS, start=1):
        p = points[place]
        ws.append([f"Phone Customer {i}", f"Synthetic parcel {i}", f"000000000{i}",  # text, not dialable
                   f"https://www.google.com/maps?q={p['lat']},{p['lng']}",
                   "Synthetic test order; leave at the gate" if i % 3 == 1 else None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class Client:
    def __init__(self, app, origin: str):
        self.c = TestClient(app, base_url="http://testserver")
        self.origin, self.csrf = origin, None

    def login(self, username: str, password: str) -> "Client":
        r = self.c.post("/api/auth/login", json={"username": username, "password": password}, headers={"Origin": self.origin})
        r.raise_for_status()
        self.csrf = self.c.get("/api/auth/session").json()["csrf_token"]
        return self

    def send(self, method: str, url: str, **kw):
        r = self.c.request(method, url, headers={"Origin": self.origin, "X-CSRF-Token": self.csrf}, **kw)
        if r.status_code >= 400:
            raise SystemExit(f"{method} {url} failed: {r.status_code}")
        return r.json()

    def get(self, url: str):
        r = self.c.get(url)
        r.raise_for_status()
        return r.json()


def ask_call_number() -> str | None:
    print("For the Call check you may enter ONE phone number you control (for example your own).")
    print("It is stored only in the local routewise_phone database and never printed. Leave blank to skip;")
    print("you can also set it later on the Mac: Orders > the order > Contact.")
    n = getpass.getpass("Number for the Call check (hidden, optional): ").strip()
    if n and (not CONTACT_CHARS.match(n) or not 7 <= len(re.sub(r"\D", "", n)) <= 15):
        raise SystemExit("That does not look like a phone number (digits, spaces, + - ( ) . ; 7-15 digits).")
    return n or None


def main() -> int:
    os.environ.setdefault("ROUTEWISE_RESOLVE_SHORT_LINKS", "false")
    load_settings()  # loads the git-ignored .env into os.environ
    url = phone_db_url()
    call_number = ask_call_number() if sys.stdin.isatty() else None
    print(f"Resetting the isolated database {DB_NAME} …")
    reset_schema(url)

    settings = load_settings(database_url=url)
    if not settings.valhalla_tiles.exists():
        raise SystemExit("Local Valhalla tiles are missing; build them first (spikes/valhalla/build_tiles.sh).")
    points = {p["id"]: p for p in json.loads((REPO_ROOT / "tests" / "fixtures" / "public_locations_du_north.json").read_text())["locations"]}
    creds = {"phone_admin": secrets.token_urlsafe(12), **{u: secrets.token_urlsafe(12) for u in RIDERS}}
    eng = create_engine(url)
    with Session(eng) as db:
        for name, pw in creds.items():
            u = User(username=name, role="admin" if name == "phone_admin" else "rider", password_hash=hash_password(pw))
            db.add(u)
            db.flush()
            if name in RIDERS:
                display, vehicle, *_ = RIDERS[name]
                db.add(Rider(user_id=u.id, display_name=display, vehicle=vehicle))
        db.commit()
        rider_ids = {n: str(db.scalar(select(Rider.id).join(User, User.id == Rider.user_id).where(User.username == n))) for n in RIDERS}
    eng.dispose()

    app = create_app(settings)
    origin = settings.allowed_origins[0]
    with TestClient(app):  # runs startup/shutdown (planning worker)
        admin = Client(app, origin).login("phone_admin", creds["phone_admin"])
        for kind in ("office", "warehouse"):
            p = points[kind]
            admin.send("PUT", f"/api/admin/depots/{kind}", json={"version": None, "label": kind.title(), "lat": p["lat"], "lng": p["lng"]})
        preview = admin.send("POST", "/api/admin/imports", files={"file": ("phone-test-orders.xlsx", workbook(points),
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        rid = admin.send("POST", f"/api/admin/imports/{preview['id']}/commit")["round_id"]
        for name, (_, vehicle, capacity, start, destination) in RIDERS.items():
            admin.send("PUT", f"/api/admin/rounds/{rid}/riders/{rider_ids[name]}", json={"vehicle": vehicle, "capacity": capacity, "start": start})
            rider = Client(app, origin).login(name, creds[name])
            rider.send("PUT", f"/api/rider/rounds/{rid}/destination", json={"kind": destination})
            rider.send("POST", f"/api/rider/rounds/{rid}/confirm", json={"config_version": rider.get(f"/api/rider/rounds/{rid}")["config_version"]})
        print("Planning on the local Valhalla tiles …")
        run = admin.send("POST", f"/api/admin/rounds/{rid}/optimize")
        for _ in range(600):
            run = admin.get(f"/api/admin/planning-runs/{run['id']}")
            if run["state"] not in ("queued", "running"):
                break
            time.sleep(0.2)
        if run["state"] != "succeeded":
            raise SystemExit(f"planning did not succeed: {run['state']} {run.get('error')}")
        plan = admin.get(f"/api/admin/rounds/{rid}/plan")
        route_a = next(r for r in plan["routes"] if r["rider"] == "Test Rider A")
        codes_a = [o["order_code"] for s in route_a["stops"] for o in s["orders"]]
        orders = {o["order_code"]: o for o in admin.get(f"/api/admin/rounds/{rid}/orders")}
        if call_number:  # contact is customer text, not planning input: the plan stays current
            first = orders[codes_a[0]]
            admin.send("PATCH", f"/api/admin/orders/{first['id']}", json={"version": first["version"], "contact": call_number})
        provenance = plan["provenance"]

    OUT.mkdir(parents=True, exist_ok=True)
    cred = OUT / "credentials.txt"
    cred.write_text("RouteWise phone test (local only; do not share or commit)\n" + "".join(f"{u}  {p}\n" for u, p in creds.items()))
    cred.chmod(0o600)
    by_coords = {(round(p["lat"], 6), round(p["lng"], 6)): p for p in points.values()}
    lines = ["Test Rider A — saved stop order (plan version 1, LIVE local Valhalla roads)",
             f"real_road={provenance.get('real_road')} recorded={provenance.get('recorded')}", ""]
    for i, code in enumerate(codes_a, start=1):
        o = orders[code]
        lat, lng = o["location"]["lat"], o["location"]["lng"]
        place = by_coords.get((round(lat, 6), round(lng, 6)), {}).get("name", "?")
        maps = "https://www.google.com/maps/dir/?" + urlencode({"api": 1, "destination": f"{lat:.6f},{lng:.6f}", "travelmode": "two-wheeler"})
        contact = "YOUR NUMBER (entered at setup)" if (i == 1 and call_number) else f"{o['contact']} (synthetic; Call must NOT be used)"
        lines += [f"Stop {i}: {code}  {o['customer_name']}", f"   place:   {place}", f"   pin:     {lat:.6f}, {lng:.6f}",
                  f"   Maps:    {maps}", f"   contact: {contact}", ""]
    others = sorted(set(orders) - set(codes_a))
    lines += ["Orders that belong to Test Rider B (must NOT appear for Rider A): " + ", ".join(others)]
    exp = OUT / "expected.txt"
    exp.write_text("\n".join(lines) + "\n")
    exp.chmod(0o600)
    print(f"Done. Round planned: Rider A has {len(codes_a)} stops, Rider B has {len(others)}.")
    print(f"Credentials: {cred.relative_to(REPO_ROOT)}   Expected stops: {exp.relative_to(REPO_ROOT)}")
    print("Call-check number: " + ("stored for Rider A's Stop 1 (not shown)" if call_number else "not set (set it in Orders if needed)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
