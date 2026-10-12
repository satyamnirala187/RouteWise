"""Bounded, validating Excel (.xlsx) import. Pure function of the uploaded bytes.

Limits (documented in docs/phase1/PHASE1-REPORT.md):
- file ≤ 2 MiB, .xlsx only (ZIP container), no macros (.xlsm / vbaProject.bin rejected)
- ZIP: ≤ 500 entries, ≤ 25 MiB total uncompressed, ≤ 100:1 per-entry ratio (zip-bomb guard)
- XML parsed through defusedxml (entity-expansion attacks blocked)
- first worksheet only; header found in the first 10 rows; ≤ 30 columns read
- ≤ 1,000 data rows (blank rows skipped); per-field length caps below
- formulas are never evaluated: a formula cell is a row error
Customer values never go to logs.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

import openpyxl

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ZIP_ENTRIES = 500
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_DATA_ROWS = 1000
MAX_COLUMNS = 30
HEADER_SEARCH_ROWS = 10
FIELD_LIMITS = {"name": 200, "product": 500, "contact": 40, "location": 2048, "instructions": 1000}

REQUIRED = ("name", "product", "contact", "location")
HEADER_ALIASES = {
    "name": ("name", "customer name"),
    "product": ("product", "products"),
    "contact": ("contact", "contact number", "phone", "phone number", "mobile"),
    "location": ("location", "location (google maps link)", "location (maps link)", "google maps link", "maps link"),
    "instructions": ("delivery instructions", "instructions"),
}
CANONICAL = {"name": "Name", "product": "Product", "contact": "Contact", "location": "Location",
             "instructions": "Delivery Instructions"}
_CONTACT_CHARS = re.compile(r"^[0-9+\-() .]+$")
_SCIENTIFIC = re.compile(r"^\d(\.\d+)?[eE]\+?\d+$")


@dataclass
class ParsedRow:
    row: int  # spreadsheet row number as the admin sees it in Excel
    values: dict[str, str | None]
    issues: list[dict] = field(default_factory=list)

    def add(self, severity: str, fld: str | None, message: str) -> None:
        self.issues.append({"severity": severity, "field": fld, "message": message})

    @property
    def has_error(self) -> bool:
        return any(i["severity"] == "error" for i in self.issues)


@dataclass
class ParseResult:
    file_errors: list[str] = field(default_factory=list)
    file_warnings: list[str] = field(default_factory=list)
    header_row: int | None = None
    mapping: dict[str, str] = field(default_factory=dict)  # spreadsheet heading -> canonical
    ignored_columns: list[str] = field(default_factory=list)
    rows: list[ParsedRow] = field(default_factory=list)


def _norm_header(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().rstrip(":").casefold()


def _check_container(data: bytes) -> str | None:
    if len(data) == 0:
        return "The file is empty."
    if len(data) > MAX_FILE_BYTES:
        return f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. Split it into smaller files."
    if not data.startswith(b"PK\x03\x04"):
        return "This is not an .xlsx file. Save the sheet as Excel Workbook (.xlsx); .xls and .csv are not accepted."
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                return "The workbook has too many internal parts."
            total = 0
            names = set()
            for info in infos:
                names.add(info.filename)
                total += info.file_size
                if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                    return "The workbook is compressed suspiciously; it was not opened."
            if total > MAX_UNCOMPRESSED_BYTES:
                return "The workbook expands to more than 25 MB; it was not opened."
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                return "This is not an Excel workbook (.xlsx)."
            if "xl/vbaProject.bin" in names or b"macroEnabled" in zf.read("[Content_Types].xml"):
                return "Macro-enabled workbooks are not accepted. Save as a plain .xlsx workbook."
    except zipfile.BadZipFile:
        return "The file is damaged or not an .xlsx workbook."
    return None


def _text(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _contact(cell, row: ParsedRow) -> str | None:
    v = cell.value
    if isinstance(v, bool):
        row.add("error", "contact", "Contact must be a phone number.")
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not v.is_integer():
            row.add("error", "contact", "Contact was stored as a decimal number; type the phone number as text.")
            return None
        digits = str(int(v))
        fmt = (getattr(cell, "number_format", "") or "").strip()
        if re.fullmatch(r"0+", fmt) and len(fmt) > len(digits):
            digits = digits.zfill(len(fmt))
            row.add("warning", "contact", "Excel stored Contact as a number; leading zeros were restored from the "
                                          "cell's display format. Please verify.")
        else:
            row.add("warning", "contact", "Excel stored Contact as a number, so any leading 0 or + prefix is already "
                                          "lost. Format the column as Text and re-import, or correct it here.")
        if abs(v) >= 1e15:
            row.add("warning", "contact", "The number is too long for Excel; digits may already be lost.")
        return digits
    s = _text(v)
    if s is None:
        return None
    if _SCIENTIFIC.match(s):
        row.add("error", "contact", "Contact looks like Excel scientific notation (e.g. 9.87E+09); digits are lost. "
                                    "Re-enter it as text.")
        return s
    if not _CONTACT_CHARS.match(s):
        row.add("error", "contact", "Contact may contain only digits, spaces, +, -, ( ) and dots.")
        return s
    n = sum(ch.isdigit() for ch in s)
    if not 7 <= n <= 15:
        row.add("warning", "contact", f"Contact has {n} digits; check that the number is complete.")
    return s


def parse_workbook(data: bytes) -> ParseResult:
    result = ParseResult()
    problem = _check_container(data)
    if problem:
        result.file_errors.append(problem)
        return result
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception:  # openpyxl raises many types for malformed parts
        result.file_errors.append("The workbook could not be read. Re-save it in Excel as .xlsx and try again.")
        return result
    try:
        if not wb.worksheets:
            result.file_errors.append("The workbook has no worksheets.")
            return result
        if len(wb.worksheets) > 1:
            result.file_warnings.append("Only the first worksheet is imported; other sheets are ignored.")
        ws = wb.worksheets[0]
        rows_iter = ws.iter_rows(max_col=MAX_COLUMNS)

        # The header is the first row (within the first 10) naming at least two known columns,
        # so a title line such as "Orders for Tuesday" above the table is skipped.
        known = {a for aliases in HEADER_ALIASES.values() for a in aliases}
        header_cells = None
        for idx, cells in enumerate(rows_iter, start=1):
            if sum(_norm_header(c.value) in known for c in cells) >= 2:
                header_cells, result.header_row = cells, idx
                break
            if idx >= HEADER_SEARCH_ROWS:
                break
        if header_cells is None:
            result.file_errors.append("No header row found in the first 10 rows. It needs the column names "
                                      "Name, Product, Contact and Location.")
            return result

        columns: dict[str, int] = {}
        for pos, cell in enumerate(header_cells):
            raw = _text(cell.value)
            if raw is None:
                continue
            key = next((k for k, aliases in HEADER_ALIASES.items() if _norm_header(raw) in aliases), None)
            if key is None:
                result.ignored_columns.append(raw)
            elif key in columns:
                result.file_errors.append(f"Column '{CANONICAL[key]}' appears more than once in the header row.")
            else:
                columns[key] = pos
                result.mapping[raw] = CANONICAL[key]
        missing = [CANONICAL[k] for k in REQUIRED if k not in columns]
        if missing:
            result.file_errors.append(
                "Missing required column(s): " + ", ".join(missing)
                + ". The header row needs Name, Product, Contact and Location (Delivery Instructions is optional)."
            )
            return result
        if result.ignored_columns:
            result.file_warnings.append("Ignored column(s): " + ", ".join(result.ignored_columns))

        data_rows = 0
        for row_no, cells in enumerate(rows_iter, start=result.header_row + 1):
            cells = list(cells)
            if not any(_text(c.value) for c in cells):
                continue
            data_rows += 1
            if data_rows > MAX_DATA_ROWS:
                result.file_errors.append(f"More than {MAX_DATA_ROWS} order rows. Split the file into smaller imports.")
                result.rows = []
                return result
            row = ParsedRow(row=row_no, values={})
            for key, pos in columns.items():
                cell = cells[pos] if pos < len(cells) else None
                if cell is not None and getattr(cell, "data_type", None) == "f":
                    row.add("error", key, f"{CANONICAL[key]} contains a formula; formulas are not evaluated. "
                                          "Paste values only.")
                    row.values[key] = None
                    continue
                value = (_contact(cell, row) if key == "contact" else _text(cell.value)) if cell is not None else None
                if value is not None and len(value) > FIELD_LIMITS[key]:
                    row.add("error", key, f"{CANONICAL[key]} is longer than {FIELD_LIMITS[key]} characters.")
                row.values[key] = value
            row.values.setdefault("instructions", None)
            for key in REQUIRED:
                if not row.values.get(key) and not any(i["field"] == key for i in row.issues):
                    row.add("error", key, f"{CANONICAL[key]} is missing.")
            result.rows.append(row)
    finally:
        wb.close()

    if not result.rows:
        result.file_errors.append("The sheet has a header row but no orders.")
    seen: dict[tuple, int] = {}
    for row in result.rows:
        v = row.values
        key = ((v.get("name") or "").casefold(), re.sub(r"\D", "", v.get("contact") or ""), v.get("location") or "")
        if all(key) and key in seen:
            row.add("warning", None, f"Looks like a duplicate of row {seen[key]}. Both are kept; delete one if it is a mistake.")
        else:
            seen.setdefault(key, row.row)
    return result
