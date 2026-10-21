"""Step 4D: `scripts/phone-server.sh` gets an explicit localhost mode for a later Android USB test
(`adb reverse tcp:8020 tcp:8020`, then http://localhost:8020 on the phone, which is a secure context).

These tests run only `--print-config` (it prints and exits before the database, the build or any server
starts), so they touch no database, no network and no device. The Wi-Fi mode stays as it was."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from routewise_api.config import REPO_ROOT
from routewise_api.main import create_app

from .conftest import Browser, make_user

SCRIPT = REPO_ROOT / "scripts" / "phone-server.sh"


def run(*args: str, env: dict | None = None, path_prefix: Path | None = None) -> subprocess.CompletedProcess:
    full = {k: v for k, v in os.environ.items() if k not in ("PHONE_HOST", "PHONE_PORT")}
    if path_prefix:
        full["PATH"] = f"{path_prefix}:{full['PATH']}"
    full.update(env or {})
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=full, timeout=30)


def test_localhost_mode_binds_loopback_and_allows_exactly_the_matching_origin():
    r = run("localhost", "--print-config")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "mode=localhost host=127.0.0.1 port=8020 allowed_origin=http://localhost:8020"


def test_localhost_mode_ignores_a_wifi_address_and_follows_the_port():
    r = run("localhost", "--print-config", env={"PHONE_HOST": "192.0.2.10", "PHONE_PORT": "8031"})
    assert r.stdout.strip() == "mode=localhost host=127.0.0.1 port=8031 allowed_origin=http://localhost:8031"


def test_wifi_mode_is_the_default_and_unchanged():
    for args in ([], ["wifi"]):
        r = run(*args, "--print-config", env={"PHONE_HOST": "192.0.2.10"})
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "mode=wifi host=192.0.2.10 port=8020 allowed_origin=http://192.0.2.10:8020"


def test_an_unknown_option_is_refused_and_nothing_starts():
    r = run("everywhere")
    assert r.returncode == 2
    assert "Unknown option: everywhere" in r.stdout and "Usage:" in r.stdout


def test_the_script_never_runs_adb_or_touches_a_device(tmp_path):
    """The owner runs `adb reverse`; the script only prints it. A fake adb on PATH records any call."""
    marker = tmp_path / "adb-was-called"
    fake = tmp_path / "bin"
    fake.mkdir()
    adb = fake / "adb"
    adb.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    adb.chmod(adb.stat().st_mode | stat.S_IEXEC)
    for args in (["localhost", "--print-config"], ["--print-config"]):
        run(*args, env={"PHONE_HOST": "192.0.2.10"}, path_prefix=fake)
    assert not marker.exists()
    # and no line of the script invokes it (it appears only inside comments and printed instructions)
    for line in SCRIPT.read_text().splitlines():
        code = line.strip()
        assert not re.match(r"^(exec\s+|sudo\s+)?adb\b", code), code


def test_both_modes_keep_the_unchanged_safety_settings():
    text = SCRIPT.read_text()
    assert 'export ROUTEWISE_ENV=development ROUTEWISE_COOKIE_SECURE=false ROUTEWISE_RESOLVE_SHORT_LINKS=false' in text
    assert 'export DATABASE_URL="${DATABASE_URL%/*}/routewise_phone"' in text   # only the isolated phone database
    assert 'export ROUTEWISE_ALLOWED_ORIGINS="$ORIGIN"' in text                 # one exact origin, never a wildcard
    assert '--host "$HOST"' in text and "0.0.0.0" not in text                    # never all interfaces
    assert "phone_db.py\" check" in text and "upgrade" not in re.sub(r"#.*|echo .*", "", text)  # it checks, never migrates or resets


@pytest.mark.parametrize("origin,ok", [
    ("http://localhost:8020", True),
    ("http://127.0.0.1:8020", False),     # the phone's browser sends localhost, so nothing else is allowed
    ("http://localhost:8021", False),
    ("http://192.0.2.10:8020", False),
    ("https://localhost:8020", False),
])
def test_the_app_accepts_only_the_exact_localhost_origin(app, settings, clock, origin, ok):
    """The server side of `localhost` mode: `ROUTEWISE_ALLOWED_ORIGINS=http://localhost:8020` and nothing broader."""
    app = create_app(replace(settings, allowed_origins=("http://localhost:8020",)), clock=clock)
    try:
        make_user(app, "rider_x", "rider")
        b = Browser(app)
        assert (b.login("rider_x", origin=origin).status_code == 200) is ok
    finally:
        app.state.planning.shutdown()
        app.state.engine.dispose()
