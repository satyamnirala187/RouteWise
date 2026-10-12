"""Prepare the isolated e2e database (routewise_e2e) for browser tests.

Resets the schema through the real migrations, creates one admin and two riders with
random passwords, seeds a synthetic round whose orders are assigned to the two riders
(assignment UI is Phase 2), writes a synthetic workbook to upload, and prints a JSON state
file path. Passwords exist only in the git-ignored state file. All data is synthetic.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from routewise_api.config import REPO_ROOT, load_settings  # noqa: E402
from routewise_api.models import Assignment, DeliveryRound, Order, Rider, User  # noqa: E402
from routewise_api.security import hash_password  # noqa: E402

STATE_DIR = REPO_ROOT / ".local" / "e2e"


def main() -> int:
    load_settings()
    url = os.environ["TEST_DATABASE_URL"].rsplit("/", 1)[0] + "/routewise_e2e"
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(str(API / "alembic.ini"))
    cfg.set_main_option("script_location", str(API / "migrations"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={url}"]})()
    command.upgrade(cfg, "head")

    creds = {name: secrets.token_urlsafe(18) for name in ("admin_e2e", "rider_a_e2e", "rider_b_e2e")}
    with Session(eng) as db:
        users = {}
        for name, pw in creds.items():
            u = User(username=name, role="admin" if name.startswith("admin") else "rider", password_hash=hash_password(pw))
            db.add(u)
            db.flush()
            users[name] = u
            if u.role == "rider":
                db.add(Rider(user_id=u.id, display_name="Rider A" if "_a_" in name else "Rider B", vehicle="scooter"))
        db.flush()
        rnd = DeliveryRound(name="Seeded round (synthetic)", created_by=users["admin_e2e"].id)
        db.add(rnd)
        db.flush()
        riders = {n: db.scalar(select(Rider).where(Rider.user_id == users[n].id)) for n in ("rider_a_e2e", "rider_b_e2e")}
        seeded = {}
        for i, owner in enumerate(["rider_a_e2e", "rider_a_e2e", "rider_b_e2e"]):
            o = Order(order_code=f"RW-E2E{i + 1:03d}", round_id=rnd.id, source_row=i + 2,
                      customer_name=f"Seed Customer {'AAB'[i]}{i + 1}", product="Synthetic parcel",
                      contact=f"0000000{i + 1:04d}", instructions="Synthetic instruction" if i == 0 else None,
                      location_link="geo:28.6883,77.2148", location_state="resolved", location_source="geo_uri",
                      lat=28.6883, lng=77.2148)
            db.add(o)
            db.flush()
            db.add(Assignment(order_id=o.id, rider_id=riders[owner].id))
            seeded.setdefault(owner, []).append(str(o.id))
        db.commit()
    eng.dispose()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    workbook = STATE_DIR / "e2e-orders.xlsx"
    _write_workbook(workbook)
    state = {"database_url": url, "passwords": creds, "seeded_orders": seeded, "workbook": str(workbook)}
    state_file = STATE_DIR / "state.json"
    state_file.write_text(json.dumps(state))
    state_file.chmod(0o600)
    print(state_file)
    return 0


def _write_workbook(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Orders for the e2e test (synthetic)"])
    ws.append(["Name", "Product", "Contact", "Location", "Delivery Instructions"])
    ws.append(["Test Customer E1", "Notebook", "09876500001",
               "https://www.google.com/maps/place/X/@28.68,77.20,17z/data=!3d28.6862643!4d77.20773", "Ring twice"])
    ws.append(["Test Customer E2", "Pens", 9876500002, "https://www.google.com/maps?q=28.6912,77.2091", None])
    ws.append(["Test Customer E3", "Bag", "+91 00000 00003", "https://www.google.com/maps/@28.68,77.20,17z", None])
    wb.save(path)


if __name__ == "__main__":
    sys.exit(main())
