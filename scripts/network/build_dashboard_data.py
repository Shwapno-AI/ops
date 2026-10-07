from __future__ import annotations

import calendar
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Outlet network data for the "Outlet network" and "Growth & momentum" pages.
# NETWORK_WORK: folder holding the downloaded workbooks (set by refresh.py).
# NETWORK_OUT:  where network.json is written (the Docker image points it at nginx).
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("NETWORK_WORK") or ROOT / "data" / "network-src")
OUTPUT_FILE = Path(os.environ.get("NETWORK_OUT") or ROOT / "data" / "network.json")

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": MAIN_NS, "r": REL_NS}


def pick_file(*names: str) -> Path:
    for name in names:
        path = DATA_DIR / name
        if path.exists():
            return path
    raise FileNotFoundError("Missing data file. Expected one of: " + ", ".join(names))


ZONE_FILE: Path
TARGET_FILE: Path
SALES_FILE: Path


def resolve_files() -> None:
    """Locate the workbooks lazily so this module can be imported by fetch_drive_data.py."""
    global ZONE_FILE, TARGET_FILE, SALES_FILE, LAST_MONTH_FILE
    ZONE_FILE = pick_file("zone-distribution.xlsx", "Zone Distribution.xlsx")
    TARGET_FILE = pick_file("day-wise-target.xlsx", "day-wise-sales-target.xlsx", "Day-wise Target.xlsx")
    SALES_FILE = pick_file("day-wise-sales.xlsx", "till-date-sales.xlsx", "Day-wise Sales.xlsx")
    LAST_MONTH_FILE = optional_file(*LAST_MONTH_NAMES)


def optional_file(*names: str) -> Path | None:
    for name in names:
        path = DATA_DIR / name
        if path.exists():
            return path
    return None


# Last-month workbook is optional: the dashboard still builds without it.
LAST_MONTH_NAMES = ("last-month.xlsx", "Last Month.xlsx", "Last month.xlsx", "last_month.xlsx")
LAST_MONTH_FILE: Path | None = None
DRIVE_MANIFEST = OUTPUT_FILE.with_name("network-sync.json")
LAST_MONTH_SHEET_CANDIDATES = ("SPLY-ALL (v5)", "SPLY-ALL (v5) (2)", "SPLY-ALL (v4)")
LAST_MONTH_CODE_HEADERS = {"code", "outlet code", "store code"}
LAST_MONTH_SALES_HEADERS = {"sales this"}


def col_to_num(col: str) -> int:
    value = 0
    for char in col:
        value = value * 26 + (ord(char) - 64)
    return value


def read_first_sheet(path: Path) -> tuple[str, list[list[object]]]:
    """Read the first worksheet using only Python's standard library."""
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared_strings.append("".join((t.text or "") for t in si.iter(f"{{{MAIN_NS}}}t")))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.find("m:sheets", NS)
        if sheets is None or len(sheets) == 0:
            raise ValueError(f"No worksheet found in {path.name}")
        first_sheet = sheets[0]
        sheet_name = first_sheet.attrib.get("name", "Sheet1")
        rel_id = first_sheet.attrib[f"{{{REL_NS}}}id"]

        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in relationships:
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib.get("Target")
                break
        if not target:
            raise ValueError(f"Could not locate worksheet XML in {path.name}")
        if target.startswith("/"):
            sheet_path = target.lstrip("/")
        elif target.startswith("xl/"):
            sheet_path = target
        else:
            sheet_path = f"xl/{target}"

        worksheet = ET.fromstring(archive.read(sheet_path))
        output: list[list[object]] = []
        for row in worksheet.findall(".//m:sheetData/m:row", NS):
            cells: dict[int, object] = {}
            for cell in row.findall("m:c", NS):
                ref = cell.attrib.get("r", "")
                match = re.match(r"([A-Z]+)", ref)
                if not match:
                    continue
                column = col_to_num(match.group(1))
                cell_type = cell.attrib.get("t")
                value_node = cell.find("m:v", NS)
                value: object = None
                if cell_type == "inlineStr":
                    inline = cell.find("m:is", NS)
                    if inline is not None:
                        value = "".join((t.text or "") for t in inline.iter(f"{{{MAIN_NS}}}t"))
                elif value_node is not None:
                    text = value_node.text or ""
                    if cell_type == "s":
                        value = shared_strings[int(text)]
                    elif cell_type == "b":
                        value = text == "1"
                    elif cell_type == "str":
                        value = text
                    else:
                        try:
                            number = float(text)
                            value = int(number) if number.is_integer() else number
                        except ValueError:
                            value = text
                cells[column] = value
            if cells:
                max_col = max(cells)
                output.append([cells.get(i) for i in range(1, max_col + 1)])
    return sheet_name, output


def read_named_sheet(path: Path, sheet_names: tuple[str, ...], max_columns: int = 120, max_rows: int = 20000) -> tuple[str, list[list[object]]]:
    """Stream one named worksheet with the standard library only.

    Uses iterparse and a hard column cap so a very wide sibling sheet in the
    same workbook never blows up memory during the GitHub Actions build.
    """
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared_strings.append("".join((t.text or "") for t in si.iter(f"{{{MAIN_NS}}}t")))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.find("m:sheets", NS)
        if sheets is None:
            raise ValueError(f"No worksheets found in {path.name}")

        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib.get("Id"): rel.attrib.get("Target", "") for rel in relationships}

        available = {}
        for sheet in sheets:
            name = sheet.attrib.get("name", "")
            target = rel_targets.get(sheet.attrib.get(f"{{{REL_NS}}}id", ""), "")
            if not target:
                continue
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = f"xl/{target}"
            available[norm(name)] = (name, target)

        chosen = None
        for wanted in sheet_names:
            if norm(wanted) in available:
                chosen = available[norm(wanted)]
                break
        if chosen is None and sheet_names == LAST_MONTH_SHEET_CANDIDATES:
            # A newer version tag (e.g. "SPLY-ALL (v6)") is still the same sheet.
            for key in sorted(available, reverse=True):
                if key.startswith("sply-all"):
                    chosen = available[key]
                    break
        if chosen is None:
            raise ValueError(
                f"{path.name} has no sheet named any of: {', '.join(sheet_names)}. "
                f"Found: {', '.join(name for name, _ in available.values())}"
            )

        sheet_name, sheet_path = chosen
        output: list[list[object]] = []
        with archive.open(sheet_path) as handle:
            cells: dict[int, object] = {}
            for event, element in ET.iterparse(handle, events=("end",)):
                tag = element.tag
                if tag == f"{{{MAIN_NS}}}c":
                    ref = element.attrib.get("r", "")
                    match = re.match(r"([A-Z]+)", ref)
                    if match:
                        column = col_to_num(match.group(1))
                        if column <= max_columns:
                            cell_type = element.attrib.get("t")
                            value_node = element.find("m:v", NS)
                            value: object = None
                            if cell_type == "inlineStr":
                                inline = element.find("m:is", NS)
                                if inline is not None:
                                    value = "".join((t.text or "") for t in inline.iter(f"{{{MAIN_NS}}}t"))
                            elif value_node is not None:
                                raw = value_node.text or ""
                                if cell_type == "s":
                                    index = int(raw)
                                    value = shared_strings[index] if index < len(shared_strings) else ""
                                elif cell_type == "b":
                                    value = raw == "1"
                                elif cell_type == "str":
                                    value = raw
                                else:
                                    try:
                                        number = float(raw)
                                        value = int(number) if number.is_integer() else number
                                    except ValueError:
                                        value = raw
                            cells[column] = value
                    element.clear()
                elif tag == f"{{{MAIN_NS}}}row":
                    if cells:
                        width = max(cells)
                        output.append([cells.get(i) for i in range(1, width + 1)])
                    cells = {}
                    element.clear()
                    if len(output) >= max_rows:
                        break
    return sheet_name, output


def read_last_month_sales() -> tuple[dict[str, float], dict[str, object]]:
    """Return {outlet code: last-month sales} plus provenance metadata."""
    if LAST_MONTH_FILE is None:
        return {}, {}

    sheet_name, rows = read_named_sheet(LAST_MONTH_FILE, LAST_MONTH_SHEET_CANDIDATES)
    header_row = -1
    code_col = sales_col = -1
    for row_index, row in enumerate(rows[:30]):
        found_code = found_sales = -1
        for i, value in enumerate(row):
            cell = norm(value)
            if found_code < 0 and cell in LAST_MONTH_CODE_HEADERS:
                found_code = i
            if found_sales < 0 and cell in LAST_MONTH_SALES_HEADERS:
                found_sales = i
        if found_code >= 0 and found_sales >= 0:
            header_row, code_col, sales_col = row_index, found_code, found_sales
            break
    if header_row < 0:
        raise ValueError(
            f"{LAST_MONTH_FILE.name} sheet '{sheet_name}' needs a 'Code' column and a 'SALES THIS' column."
        )

    # The row above the header usually carries the period label, e.g. "Same Day SPLY Jul 1-29".
    period_label = ""
    if header_row > 0:
        banner = rows[header_row - 1]
        for i in range(sales_col, -1, -1):
            if i < len(banner) and str(banner[i] or "").strip():
                period_label = str(banner[i]).strip()
                break

    totals: dict[str, float] = {}
    for row in rows[header_row + 1:]:
        if code_col >= len(row) or row[code_col] in (None, ""):
            continue
        code = str(row[code_col]).strip().upper()
        if not code or norm(code) in LAST_MONTH_CODE_HEADERS or "total" in norm(code):
            continue
        raw = row[sales_col] if sales_col < len(row) else None
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        totals[code] = totals.get(code, 0.0) + value

    meta = {
        "fileName": LAST_MONTH_FILE.name,
        "sheetName": sheet_name,
        "columnLabel": "SALES THIS",
        "periodLabel": period_label,
        "outletCount": len(totals),
    }
    return totals, meta


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("_", " "))


def excel_date_to_iso(value: object) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def clean_int_string(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value).strip()


def clean_phone(value: object) -> str:
    text = clean_int_string(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits and len(digits) == 10 and not digits.startswith("0"):
        digits = "0" + digits
    return digits or text


def safe_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def find_header(rows: list[list[object]], required: set[str], aliases: dict[str, set[str]] | None = None, limit: int = 20) -> tuple[int, dict[str, int]]:
    aliases = aliases or {key: {key} for key in required}
    for row_index, row in enumerate(rows[:limit]):
        found: dict[str, int] = {}
        for i, value in enumerate(row):
            cell = norm(value)
            for key, names in aliases.items():
                if cell in names and key not in found:
                    found[key] = i
        if required.issubset(found):
            return row_index, found
    raise ValueError("Could not find the expected header row.")


SOURCE_COLUMNS = [
    ("code", "Outlet code"), ("outletName", "Outlet name"),
    ("targetToDate", "Till-date target (BDT)"), ("salesToDate", "Till-date sales (BDT)"),
    ("salesGapToDate", "Till-date gap (BDT)"), ("salesAchievement", "Till-date achievement"),
    ("lastMonthSales", "Last month sales (BDT)"), ("momGrowth", "MoM growth"),
    ("monthlyTarget", "Monthly sales target (BDT)"), ("projectedSales", "Projected monthly sales (BDT)"),
    ("projectedGap", "Projected gap (BDT)"), ("projectedAchievement", "Projected achievement"),
    ("projectedVsLastMonth", "Projected vs last month (BDT)"),
    ("leader", "RHO"), ("rhoId", "RHO ID"), ("rhoPhone", "RHO Phone"),
    ("zonal", "Zonal"), ("zonalId", "Zonal ID"), ("zonalPhone", "Zonal Phone"),
    ("format", "Format"), ("division", "Division"), ("district", "District"),
    ("cityType", "Location type (Dv, Ds, T)"), ("floorType", "Floor type"),
    ("layoutShape", "Layout shape"), ("status", "Store status"), ("pnpStatus", "PNP status"),
    ("sft", "SFT"), ("launchDate", "Launching date"), ("locationType", "Location type"),
    ("regionalHead", "Regional head"), ("area", "Area"), ("density", "Population density"),
    ("incomeLevel", "Income level")
]


def read_drive_manifest() -> dict:
    if not DRIVE_MANIFEST.exists():
        return {}
    try:
        return json.loads(DRIVE_MANIFEST.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def build() -> dict:
    resolve_files()
    drive = read_drive_manifest()
    zone_sheet, zone_rows = read_first_sheet(ZONE_FILE)
    target_sheet, target_rows = read_first_sheet(TARGET_FILE)
    sales_sheet, sales_rows = read_first_sheet(SALES_FILE)
    last_month_map, last_month_meta = read_last_month_sales()

    if len(zone_rows) < 2 or len(target_rows) < 2 or len(sales_rows) < 2:
        raise ValueError("One or more source workbooks do not contain the expected data rows.")

    # Target workbook: find Outlet Code + Outlet Name row; all following date columns become daily targets.
    target_header_row, target_cols = find_header(
        target_rows,
        {"code", "name"},
        {"code": {"outlet code", "code", "store code"}, "name": {"outlet name", "store name"}},
    )
    target_header = target_rows[target_header_row]
    # Only the first column of each date counts: the October 2026 workbook repeats the 1-31 date headings in
    # further blocks to the right (other daily figures and shares), which must not overwrite the taka target.
    date_columns: list[tuple[int, str]] = []
    seen_dates: set[str] = set()
    for i, value in enumerate(target_header):
        if i in (target_cols["code"], target_cols["name"]):
            continue
        date = excel_date_to_iso(value)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date) and date not in seen_dates:
            seen_dates.add(date)
            date_columns.append((i, date))
    if not date_columns:
        raise ValueError(f"No daily target date columns found in {TARGET_FILE.name}.")

    target_map: dict[str, dict[str, float]] = {}
    target_names: dict[str, str] = {}
    for row in target_rows[target_header_row + 1:]:
        if target_cols["code"] >= len(row) or row[target_cols["code"]] in (None, ""):
            continue
        code = str(row[target_cols["code"]]).strip().upper()
        name = row[target_cols["name"]] if target_cols["name"] < len(row) else ""
        target_names[code] = str(name or "").strip()
        target_map[code] = {date: safe_float(row[i] if i < len(row) else 0) for i, date in date_columns}

    # Day-wise sales workbook.
    sales_header_row, sales_cols = find_header(
        sales_rows,
        {"code", "date", "sales"},
        {
            "code": {"outlet code", "code", "store code", "outlet"},
            "date": {"date", "sales date", "business date", "transaction date", "pos date"},
            "sales": {"pos nsi", "daily sales", "actual sales", "net sales", "sales"},
        },
    )
    actual_map: dict[str, dict[str, float]] = {}
    sales_dates: set[str] = set()
    valid_sales_rows = 0
    for row in sales_rows[sales_header_row + 1:]:
        if sales_cols["code"] >= len(row) or row[sales_cols["code"]] in (None, ""):
            continue
        code = str(row[sales_cols["code"]]).strip().upper()
        date = excel_date_to_iso(row[sales_cols["date"]] if sales_cols["date"] < len(row) else "")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        value = safe_float(row[sales_cols["sales"]] if sales_cols["sales"] < len(row) else 0)
        daily = actual_map.setdefault(code, {})
        daily[date] = daily.get(date, 0.0) + value
        sales_dates.add(date)
        valid_sales_rows += 1

    # Outlet master workbook.
    zone_header_row, _ = find_header(
        zone_rows,
        {"code", "name"},
        {"code": {"code", "outlet code", "store code"}, "name": {"outlet name", "store name"}},
    )
    headers = zone_rows[zone_header_row]
    index = {str(header).strip(): i for i, header in enumerate(headers) if header not in (None, "")}

    def value(row: list[object], header: str) -> object:
        i = index.get(header)
        return row[i] if i is not None and i < len(row) else None

    records = []
    for row in zone_rows[zone_header_row + 1:]:
        code_value = value(row, "CODE") if "CODE" in index else value(row, "Outlet Code")
        if code_value in (None, ""):
            continue
        code = str(code_value).strip().upper()
        launch_date = excel_date_to_iso(value(row, "Launching Date"))
        try:
            launch_year = int(launch_date[:4]) if launch_date else None
        except ValueError:
            launch_year = None

        records.append({
            "code": code,
            "outletName": str(value(row, "Outlet Name") or target_names.get(code, "")).strip(),
            "regionalHead": str(value(row, "Regional Head HR Name") or "").strip(),
            "leader": str(value(row, "Leader") or "").strip(),
            "rhoId": clean_int_string(value(row, "Leader ID") or value(row, "Regional Head ID")),
            "rhoPhone": clean_phone(value(row, "Leader Contact") or value(row, "Regional Head Contact")),
            "zonal": str(value(row, "Zonal") or value(row, "Zonal HR Name") or "").strip(),
            "zonalId": clean_int_string(value(row, "Zonal ID")),
            "zonalPhone": clean_phone(value(row, "Zonal Contact")),
            "launchDate": launch_date,
            "launchYear": launch_year,
            "sft": safe_float(value(row, "SFT")),
            "format": str(value(row, "Format") or "").strip(),
            "division": str(value(row, "Division") or "").strip(),
            "district": str(value(row, "District") or "").strip(),
            "area": str(value(row, "Area") or "").strip(),
            "pnpStatus": str(value(row, "PNP Non PNP status") or "").strip(),
            "status": str(value(row, "Status") or "").strip(),
            "geoLocation": str(value(row, "Geo Location") or "").strip(),
            "locationType": str(value(row, "Location Type") or "").strip(),
            "cityType": str(value(row, "Location Type(Dv,Ds,T)") or "").strip(),
            "density": str(value(row, "Population Density") or "").strip(),
            "incomeLevel": str(value(row, "Income level") or "").strip(),
            "floorType": str(value(row, "Floor type") or "").strip(),
            "layoutShape": str(value(row, "Layout shape") or "").strip(),
            "dailySalesTargets": target_map.get(code, {}),
            "dailySalesActuals": actual_map.get(code, {}),
            "lastMonthSales": last_month_map.get(code),
        })

    # Every outlet in the day-wise sales file (outlet master or not) with the days it sold, for the active-outlet
    # count: [code, name, in outlet master, days of the month with sales above zero]. Rows that are not outlet
    # codes (the "Total (…)" footer, "Undf# 74" and the like) are left out and counted.
    master_codes = {record["code"] for record in records}
    sales_outlets, not_outlet_codes = [], []
    for code, daily in sorted(actual_map.items()):
        if not re.match(r"^[A-Z]{1,2}\d{2,4}$", code):
            not_outlet_codes.append(code)
            continue
        days = sorted(int(date[8:10]) for date, amount in daily.items() if amount > 0)
        sales_outlets.append([code, target_names.get(code, ""), code in master_codes, days])

    target_dates = [date for _, date in date_columns]
    report_month = target_dates[0][:7] if target_dates else ""
    sales_start = min(sales_dates) if sales_dates else ""
    sales_through = max(sales_dates) if sales_dates else ""
    if sales_through and report_month and sales_through[:7] != report_month:
        raise ValueError(f"Latest sales date {sales_through} is not in target month {report_month}. Update day-wise sales and day-wise target together.")

    days_in_month = 0
    previous_month = ""
    previous_month_label = ""
    if report_month:
        year, month = [int(v) for v in report_month.split("-")]
        days_in_month = calendar.monthrange(year, month)[1]
        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        previous_month = f"{prev_year:04d}-{prev_month:02d}"
        previous_month_label = f"{calendar.month_abbr[prev_month]} {prev_year}"

    matched_last_month = sum(1 for record in records if record.get("lastMonthSales") is not None)
    last_month = dict(last_month_meta)
    if last_month:
        last_month.update({
            "month": previous_month,
            "monthLabel": previous_month_label,
            "matchedOutlets": matched_last_month,
            "total": round(sum(record["lastMonthSales"] for record in records if record.get("lastMonthSales") is not None), 2),
        })

    source = {
        "fileName": "Google Drive auto-sync" if drive else "GitHub /data auto-refresh",
        "sheetName": zone_sheet,
        "label": ("Google Drive snapshot" if drive else "Auto-built GitHub snapshot")
        + (f" · Sales through {sales_through}" if sales_through else ""),
        "drive": {
            "folderUrl": drive.get("folderUrl", ""),
            "syncedAt": drive.get("syncedAt", ""),
            "files": {role: info.get("driveName", "") for role, info in (drive.get("files") or {}).items()},
        } if drive else {},
        "columns": [{"id": f"field_{key}", "label": label, "fieldKey": key} for key, label in SOURCE_COLUMNS],
        "reportMonth": report_month,
        "reportMonthSource": TARGET_FILE.name,
        "salesThroughDate": sales_through,
        "salesThroughDateSource": SALES_FILE.name,
        "salesStartDate": sales_start,
        "salesEndDate": sales_through,
        "daysInMonth": days_in_month,
        "previousMonth": previous_month,
        "previousMonthLabel": previous_month_label,
        "lastMonth": last_month,
        "projectionMethod": "Actual sales through the selected end date plus separate average-sales forecasts for remaining Fridays, Saturdays, and Sunday-Thursday days",
        "sourceFiles": {
            "outletMaster": ZONE_FILE.name,
            "dayWiseSales": SALES_FILE.name,
            "dayWiseTarget": TARGET_FILE.name,
            "lastMonth": LAST_MONTH_FILE.name if LAST_MONTH_FILE else "",
        },
        "sourceSheets": {
            "outletMaster": zone_sheet,
            "dayWiseSales": sales_sheet,
            "dayWiseTarget": target_sheet,
        },
    }

    return {
        "source": source,
        "meta": {
            "reportMonth": report_month,
            "previousMonth": previous_month,
            "salesThroughDate": sales_through,
            "sourceRows": {
                "outlets": len(records),
                "targetOutlets": len(target_map),
                "salesRows": valid_sales_rows,
                "lastMonthOutlets": matched_last_month,
            },
        },
        "rows": records,
        "salesOutlets": sales_outlets,
        "salesNonOutletCodes": [code for code in not_outlet_codes if not code.startswith("TOTAL")],
    }


def main() -> None:
    payload = build()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename so nginx never serves a half-written file.
    tmp = OUTPUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUTPUT_FILE)
    last_month = payload["source"].get("lastMonth") or {}
    print(
        f"Wrote {OUTPUT_FILE} with {len(payload['rows'])} outlets; "
        f"sales through {payload['source']['salesThroughDate']}; "
        + (
            f"last month ({last_month.get('monthLabel') or 'n/a'}) matched on "
            f"{last_month.get('matchedOutlets', 0)} outlets from {last_month.get('fileName')}."
            if last_month
            else "no last-month workbook found."
        )
    )


if __name__ == "__main__":
    main()
