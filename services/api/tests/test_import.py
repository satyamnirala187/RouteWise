"""Excel import: limits, headers, rows, contacts, preview → commit/discard. Synthetic data only."""

import io
import zipfile

from sqlalchemy import select

from routewise_api import importer
from routewise_api.models import ImportBatch, Order

from .conftest import HEADER, PIN, upload, xlsx

ROW_OK = ["Test Customer 01", "Notebook", "09876500001", PIN, "Ring twice"]


def issues(row, severity=None):
    return [i for i in row["issues"] if severity is None or i["severity"] == severity]


def test_valid_file_previews_then_commits_with_unique_ids(admin, db):
    data = xlsx([HEADER, ROW_OK, ["Test Customer 02", "Pens x3", "+91 00000 00002", PIN, None]])
    r = upload(admin, data)
    assert r.status_code == 201
    p = r.json()
    assert p["state"] == "preview" and p["summary"]["can_commit"] and p["summary"]["total_rows"] == 2
    assert p["summary"]["mapping"] == {"Name": "Name", "Product": "Product", "Contact": "Contact",
                                       "Location": "Location", "Delivery Instructions": "Delivery Instructions"}
    first, second = p["rows"]
    assert first["row"] == 2 and first["values"]["contact"] == "09876500001"  # leading zero kept
    assert second["values"]["contact"] == "+91 00000 00002" and second["values"]["instructions"] is None
    assert first["location"]["state"] == "resolved" and first["location"]["lat"] == 28.6862643
    assert db.scalar(select(Order).limit(1)) is None  # nothing saved before commit

    c = admin.send("POST", f"/api/admin/imports/{p['id']}/commit")
    assert c.status_code == 200 and c.json()["orders_created"] == 2
    orders = db.scalars(select(Order).order_by(Order.source_row)).all()
    assert [o.order_code for o in orders] == ["RW-001001", "RW-001002"]
    assert [o.status for o in orders] == ["Pending", "Pending"]
    assert orders[0].contact == "09876500001" and orders[1].instructions is None
    batch = db.get(ImportBatch, p["id"])
    assert batch.state == "committed" and batch.rows is None  # preview copy of customer data dropped
    assert admin.send("POST", f"/api/admin/imports/{p['id']}/commit").status_code == 409


def test_order_ids_stay_unique_across_imports(admin, db):
    for _ in range(2):
        p = upload(admin, xlsx([HEADER, ROW_OK])).json()
        admin.send("POST", f"/api/admin/imports/{p['id']}/commit")
    codes = db.scalars(select(Order.order_code)).all()
    assert len(codes) == len(set(codes)) == 2


def test_header_aliases_extra_columns_and_optional_instructions_column(admin):
    data = xlsx([["Customer Name", "Products", "Phone", "Location (Google Maps link)", "Notes"],
                 ["Test Customer 03", "Bag", "011-0000000", PIN, "x"]])
    p = upload(admin, data).json()
    s = p["summary"]
    assert s["can_commit"] and s["ignored_columns"] == ["Notes"]
    assert s["mapping"]["Location (Google Maps link)"] == "Location"
    assert p["rows"][0]["values"]["instructions"] is None  # optional column absent is fine


def test_missing_required_column_is_a_file_error(admin):
    p = upload(admin, xlsx([["Name", "Product", "Location"], ["Test Customer", "Box", PIN]])).json()
    assert p["summary"]["can_commit"] is False
    assert "Missing required column(s): Contact" in p["summary"]["file_errors"][0]
    assert admin.send("POST", f"/api/admin/imports/{p['id']}/commit").status_code == 422


def test_duplicate_header_is_a_file_error(admin):
    p = upload(admin, xlsx([["Name", "Product", "Contact", "Location", "Phone"], ["a", "b", "1234567", PIN, "x"]])).json()
    assert any("more than once" in e for e in p["summary"]["file_errors"])


def test_row_errors_have_row_numbers_and_block_commit(admin):
    data = xlsx([["Orders for Tuesday"], [], HEADER,
                 ["Test Customer 04", None, "00000000004", PIN, None],      # row 4: product missing
                 ["Test Customer 05", "Box", "call me", PIN, None],         # row 5: bad contact
                 ["Test Customer 06", "Box", "00000000006", None, None]])   # row 6: location missing
    p = upload(admin, data).json()
    assert p["summary"]["header_row"] == 3
    by_row = {r["row"]: r for r in p["rows"]}
    assert issues(by_row[4], "error")[0]["field"] == "product"
    assert "digits" in issues(by_row[5], "error")[0]["message"]
    assert issues(by_row[6], "error")[0]["message"] == "Location is missing."
    assert p["summary"]["rows_with_errors"] == 3 and not p["summary"]["can_commit"]
    assert admin.send("POST", f"/api/admin/imports/{p['id']}/commit").status_code == 422


def test_formula_cells_are_never_evaluated(admin):
    p = upload(admin, xlsx([HEADER, ["Test Customer 07", "=1+1", "00000000007", PIN, None]])).json()
    err = issues(p["rows"][0], "error")[0]
    assert err["field"] == "product" and "formula" in err["message"]


def test_numeric_contacts_warn_and_recover_padded_zeros(admin):
    data = xlsx([HEADER,
                 ["Test Customer 08", "Box", 9876500008, PIN, None],      # row 2: plain number
                 ["Test Customer 09", "Box", 9876500009, PIN, None],      # row 3: zero-padded display format
                 ["Test Customer 10", "Box", "9.8765E+09", PIN, None]],   # row 4: scientific text
                number_formats={(3, 3): "00000000000"})
    rows = {r["row"]: r for r in upload(admin, data).json()["rows"]}
    assert rows[2]["values"]["contact"] == "9876500008"
    assert "already lost" in issues(rows[2], "warning")[0]["message"]
    assert rows[3]["values"]["contact"] == "09876500009"
    assert "restored" in issues(rows[3], "warning")[0]["message"]
    assert "scientific" in issues(rows[4], "error")[0]["message"]


def test_unresolved_and_ambiguous_locations_import_with_needs_pin_warning(admin):
    data = xlsx([HEADER,
                 ["Test Customer 11", "Box", "00000000011", "https://www.google.com/maps/@28.68,77.20,17z", None],
                 ["Test Customer 12", "Box", "00000000012", "near the metro gate", None],
                 ["Test Customer 13", "Box", "00000000013", "https://maps.app.goo.gl/AbCdEf", None]])
    p = upload(admin, data).json()
    assert p["summary"]["can_commit"] and p["summary"]["needs_pin"] == 3
    notes = [r["location"]["note"] for r in p["rows"]]
    assert "map view centre" in notes[0] and "not a Google Maps link" in notes[1]
    assert "short link not checked (link checks disabled)" in notes[2]


def test_pin_outside_service_area_is_flagged(admin):
    far = "https://www.google.com/maps?q=12.9716,77.5946"  # Bengaluru: outside DU service area
    row = upload(admin, xlsx([HEADER, ["Test Customer 14", "Box", "00000000014", far, None]])).json()["rows"][0]
    assert row["location"]["state"] == "resolved" and row["location"]["in_service_area"] is False
    assert "outside" in issues(row, "warning")[0]["message"]


def test_duplicates_are_flagged_not_dropped(admin):
    p = upload(admin, xlsx([HEADER, ROW_OK, ROW_OK])).json()
    assert len(p["rows"]) == 2 and "duplicate of row 2" in issues(p["rows"][1], "warning")[0]["message"]
    assert p["summary"]["can_commit"]


def test_other_sheets_warn_and_blank_rows_are_skipped(admin):
    p = upload(admin, xlsx([HEADER, [], ROW_OK, [None, None, None, None, None]], extra_sheet=True)).json()
    assert p["summary"]["total_rows"] == 1 and p["rows"][0]["row"] == 3
    assert any("first worksheet" in w for w in p["summary"]["file_warnings"])


def test_rejects_wrong_types_and_non_xlsx(admin):
    for data, name in [(b"Name,Product\n", "orders.csv"), (b"\xd0\xcf\x11\xe0legacy", "orders.xls"),
                       (b"not a zip at all", "orders.xlsx"), (b"", "orders.xlsx")]:
        r = upload(admin, data, filename=name)
        if r.status_code == 400:
            assert "xlsx" in str(r.json()).lower()
        else:
            assert r.status_code == 201 and r.json()["summary"]["file_errors"], name


def test_macro_workbook_rejected(admin):
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx([HEADER, ROW_OK]))) as src, zipfile.ZipFile(buf, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("xl/vbaProject.bin", b"\x00" * 64)
    errs = upload(admin, buf.getvalue()).json()["summary"]["file_errors"]
    assert "Macro-enabled" in errs[0]


def test_zip_bomb_rejected_before_parsing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", b"0" * (20 * 1024 * 1024))  # ~20 MB of zeros, tiny compressed
    data = buf.getvalue()
    assert len(data) < importer.MAX_FILE_BYTES
    assert "compressed suspiciously" in importer.parse_workbook(data).file_errors[0]


def test_row_and_size_limits(admin):
    many = xlsx([HEADER] + [[f"Test Customer {i}", "Box", f"0000{i:07d}", PIN, None] for i in range(1001)])
    assert "More than 1000" in upload(admin, many).json()["summary"]["file_errors"][0]
    too_big = b"PK\x03\x04" + b"\x00" * (importer.MAX_FILE_BYTES + 10)
    r = upload(admin, too_big)
    assert r.status_code in (201, 413)
    if r.status_code == 201:
        assert "larger than 2 MB" in r.json()["summary"]["file_errors"][0]
    huge = b"PK\x03\x04" + b"\x00" * (4 * 1024 * 1024)
    assert upload(admin, huge).status_code == 413  # stopped by the streaming body limit


def test_field_length_limits(admin):
    p = upload(admin, xlsx([HEADER, ["N" * 201, "Box", "00000000015", PIN, None]])).json()
    assert "longer than 200" in issues(p["rows"][0], "error")[0]["message"]


def test_discard_and_expiry(admin, clock, db):
    p = upload(admin, xlsx([HEADER, ROW_OK])).json()
    assert admin.send("DELETE", f"/api/admin/imports/{p['id']}").status_code == 200
    assert db.get(ImportBatch, p["id"]).rows is None
    assert admin.send("POST", f"/api/admin/imports/{p['id']}/commit").status_code == 409
    p2 = upload(admin, xlsx([HEADER, ROW_OK])).json()
    clock.advance(hours=1, seconds=1)
    assert admin.send("POST", f"/api/admin/imports/{p2['id']}/commit").status_code == 410
    assert db.scalar(select(Order).limit(1)) is None
