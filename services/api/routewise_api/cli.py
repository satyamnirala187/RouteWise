"""Local administration commands. Passwords are typed at a prompt (or piped on stdin);
they are never accepted as command-line arguments, so they don't land in shell history.

  .venv/bin/python -m routewise_api.cli create-user --username admin1 --role admin
  .venv/bin/python -m routewise_api.cli create-user --username rider1 --role rider --name "Rider One" --vehicle scooter
  .venv/bin/python -m routewise_api.cli set-password --username rider1
  .venv/bin/python -m routewise_api.cli deactivate --username rider1
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from .accounts import deactivate_user, revoke_sessions
from .config import load_settings
from .db import make_engine, make_session_factory
from .models import Rider, User
from .security import MIN_PASSWORD_LENGTH, hash_password


def _read_password() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass(f"Password (min {MIN_PASSWORD_LENGTH} chars): ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    return first


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="routewise_api.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--username", required=True)
    c.add_argument("--role", choices=["admin", "rider"], required=True)
    c.add_argument("--name", help="rider display name")
    c.add_argument("--vehicle", choices=["scooter", "bike"])
    for name in ("set-password", "deactivate"):
        sub.add_parser(name).add_argument("--username", required=True)
    args = ap.parse_args(argv)

    settings = load_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    username = args.username.strip().lower()
    with factory() as db:
        if args.cmd == "create-user":
            if db.scalar(select(User).where(User.username == username)):
                raise SystemExit("That username already exists")
            user = User(username=username, role=args.role, password_hash=hash_password(_read_password()))
            db.add(user)
            db.flush()
            if args.role == "rider":
                db.add(Rider(user_id=user.id, display_name=args.name or username, vehicle=args.vehicle))
            db.commit()
            print(f"created {args.role} '{username}'")
        else:
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                raise SystemExit("No such user")
            now = datetime.now(timezone.utc)
            if args.cmd == "set-password":
                # Ends every existing session; not planning input, so no plan is invalidated.
                user.password_hash = hash_password(_read_password())
                revoke_sessions(db, user.id, now)
                db.commit()
                print(f"set-password: done for '{username}'")
            else:
                done = deactivate_user(db, user.id, now)
                print(f"deactivate: done for '{username}'"
                      + (f"; planning input changed in {len(done.rounds_invalidated)} round(s), re-plan them"
                         if done.rounds_invalidated else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
