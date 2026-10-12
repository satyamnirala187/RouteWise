"""Criteria 1 and 11 support: pinned environment, import-library compatibility, cost model;
plus opt-in live provider checks."""

import os
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from routewise_spike.costs import monthly_cost_usd, project

LOCK = Path(__file__).resolve().parents[1] / "requirements.lock"


def test_runtime_matches_pinned_lock():
    assert sys.version_info[:2] == (3, 14)
    pins = dict(line.strip().split("==") for line in LOCK.read_text().splitlines() if "==" in line)
    for pkg in ("ortools", "fastapi", "httpx", "pandas", "openpyxl", "pytest"):
        assert version(pkg) == pins[pkg], pkg


def test_pandas_openpyxl_preserve_contacts_and_do_not_evaluate_formulas(tmp_path):
    import openpyxl
    import pandas as pd

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Product", "Contact", "Location (Google Maps link)", "Delivery Instructions"])
    ws.append(["Test Customer A", "Box", "00012345678", "https://www.google.com/maps?q=12.97,77.59", None])
    ws.append(["Test Customer B", "Bag", "+00 00000 00000", "https://www.google.com/maps?q=12.98,77.60", "=1+1"])
    path = tmp_path / "synthetic.xlsx"
    wb.save(path)
    df = pd.read_excel(path, dtype=str, engine="openpyxl")
    assert df.loc[0, "Contact"] == "00012345678"
    assert df.loc[1, "Contact"] == "+00 00000 00000"
    assert pd.isna(df.loc[0, "Delivery Instructions"])
    assert df.loc[1, "Delivery Instructions"] != "2"  # formula was not evaluated


def test_tiered_monthly_cost():
    assert monthly_cost_usd(1_000, "Enterprise (TWO_WHEELER)") == 0
    assert monthly_cost_usd(101_000, "Enterprise (TWO_WHEELER)") == pytest.approx(99 * 15 + 1 * 12)
    assert monthly_cost_usd(10_000, "Essentials (DRIVE, basic)") == 0
    assert monthly_cost_usd(20_000, "Essentials (DRIVE, basic)") == pytest.approx(50.0)


def test_projection_counts_elements_as_origins_times_destinations():
    p = project(20, 3)
    assert p.locations == 25 and p.initial_elements == 625 and p.initial_requests == 1
    assert project(100, 8).initial_requests == 25  # 110 locations -> 5 x 5 tiles


live = pytest.mark.skipif(os.environ.get("ROUTEWISE_LIVE_TESTS") != "1", reason="set ROUTEWISE_LIVE_TESTS=1")


@pytest.mark.live
@live
def test_live_osrm_returns_real_asymmetric_road_matrix(locations):
    from routewise_spike.matrix.osrm import OSRMTableProvider

    pts = [locations[i] for i in ("office", "ub_city", "forum_koramangala", "shivajinagar_bus")]
    m = OSRMTableProvider().compute(pts, pts, "car_proxy")
    assert m.provenance.real_road and not m.provenance.recorded
    ids = [p.id for p in pts]
    assert any(m.get(a, b).distance_m != m.get(b, a).distance_m for a in ids for b in ids if a < b)


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("GOOGLE_MAPS_API_KEY"),
                    reason="BLOCKED: GOOGLE_MAPS_API_KEY not set (no credentials / no approved spend)")
def test_live_google_routes_two_wheeler_matrix(locations):
    from routewise_spike.matrix.google_routes import GoogleRoutesMatrixProvider

    pts = [locations[i] for i in ("office", "ub_city", "forum_koramangala")]
    m = GoogleRoutesMatrixProvider(os.environ["GOOGLE_MAPS_API_KEY"]).compute(pts, pts, "two_wheeler")
    assert m.provenance.real_road and m.provenance.profile == "TWO_WHEELER"
