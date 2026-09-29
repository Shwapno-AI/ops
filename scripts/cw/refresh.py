#!/usr/bin/env python3
"""Refresh data/cw.json for the Consumable & wastage pages.

Reads the mother Google Drive folder that holds every dashboard's data,
sub-folders included. Every file is recognised by its STRUCTURE, never by its
name or folder:

* SAP movement export — a Posting Date + Plant + Amount header. Movement type
  551 (write-off) is wastage; Z21/Z22 (consumable issue / reversal) is
  consumable. If the movement type is unfamiliar, material codes starting 60
  (consumable stores) decide.
* Sales till date — Outlet (Code) + Date + (Article) Division + POS NSI.
* Zone Distribution — CODE + Outlet Name + Format + Division + District +
  PNP Non PNP status + Status.
* Targets — a Final Criteria column with the three target % columns.

When two files of the same kind are found, the one whose data runs latest
wins (Zone Distribution and targets: the most recently modified in Drive).

Exit code 1 = the refresh failed; cw.json is left untouched, so the dashboard
keeps showing the last good data.
"""
import csv
import io
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "network"))

import build_data as bd  # noqa: E402
import fetch_drive_data as drive  # noqa: E402  (stdlib public-folder listing and download)
from openpyxl import load_workbook  # noqa: E402

FOLDER = (os.environ.get("CW_FOLDER_ID") or os.environ.get("DATA_FOLDER_ID") or "1Te9stxbcBsIIO8bNElPuDXXPovkk4v1l").strip()
OUT = Path(os.environ.get("CW_OUT") or ROOT / "data" / "cw.json")
DATA_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".txt", ".csv", ".tsv")
WASTAGE_MOVES = {"551", "552"}
CONSUMABLE_MOVES = {"Z21", "Z22", "201", "202"}
def is_sales(heads):
    """A sales till-date header: an outlet, a date, a division and POS NSI column, under any of the names the
    reader accepts (e.g. "Outlet Code" with "Article Division", or "Outlet" with "Division")."""
    return all(heads & aliases for aliases in bd.SALES_ALIASES.values())
ZONE_HEADERS = {"code", "outlet name", "format", "division", "district", "pnp non pnp status", "status"}
TARGET_HEADERS = {"final criteria", *(h.casefold() for h in bd.TARGET_COLUMNS.values())}


def log(msg):
    print(msg, flush=True)


def norm(v):
    return bd.clean_text(v).casefold()


def sap_kind(path):
    """'consumable' / 'wastage' plus the latest posting date, or None if this is not a SAP export."""
    columns, moves, prefixes, latest = None, Counter(), Counter(), None
    try:
        for n, row in enumerate(bd.iter_sap_rows(path)):
            cells = [bd.clean_text(c) for c in row]
            if columns is None:
                if n >= 200:
                    return None
                columns = bd.locate_sap_header(cells)
                continue
            get = lambda f: cells[columns[f]] if f in columns and columns[f] < len(cells) else ""  # noqa: E731
            if not bd.normalize_outlet_code(get("plant")):
                continue
            moves[get("movement").upper()] += 1
            prefixes[get("material")[:2]] += 1
            d = bd.parse_date(get("postingDate"))
            if d and (latest is None or d > latest):
                latest = d
    except Exception:  # noqa: BLE001 - unreadable file is simply "not a SAP export"
        return None
    if columns is None or not moves:
        return None
    w = sum(c for m, c in moves.items() if m in WASTAGE_MOVES)
    c = sum(c for m, c in moves.items() if m in CONSUMABLE_MOVES)
    if w or c:
        return ("wastage" if w >= c else "consumable"), latest
    return ("consumable" if prefixes.get("60", 0) > sum(prefixes.values()) / 2 else "wastage"), latest


def sheet_headers(path, rows=15):
    """Yield (raw cells, normalised header set) for the first rows of every sheet."""
    wb = load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True, max_row=rows):
                yield [bd.clean_text(v) for v in row], {norm(v) for v in row if v not in (None, "")}
    finally:
        wb.close()


def classify(path):
    """Cheap first look at the top rows; the full SAP scan only runs on a SAP-shaped file."""
    if path.read_bytes()[:4] != b"PK\x03\x04":
        return sap_kind(path) or table_kind(path)  # legacy .xls or text export
    for cells, heads in sheet_headers(path):
        if bd.locate_sap_header(cells) is not None:
            return sap_kind(path)
        if is_sales(heads):
            return "sales", sales_latest(path)
        if ZONE_HEADERS <= heads:
            return "zones", None
        if TARGET_HEADERS <= heads:
            return "targets", None
    return None


def table_kind(path):
    """'sales' / 'zones' / 'targets' for an Excel or text table, with a freshness value."""
    data = path.read_bytes()
    if data[:4] == b"PK\x03\x04":
        for ws, i, heads in sheet_headers(path):
            if is_sales(heads):
                return "sales", sales_latest(path)
            if ZONE_HEADERS <= heads:
                return "zones", None
            if TARGET_HEADERS <= heads:
                return "targets", None
        return None
    # Text: the target file is tab-delimited; look at its first line.
    text = data[:4096].decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    heads = {norm(h) for h in re.split(r"[\t,;|]", first)}
    return ("targets", None) if TARGET_HEADERS <= heads else None


def sales_latest(path):
    wb = load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True)
    try:
        ws = wb["Comparative"] if "Comparative" in wb.sheetnames else wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        idx = {norm(v): i for i, v in enumerate(next(rows))}.get("date")
        latest = None
        for r in rows:
            d = bd.parse_date(r[idx]) if idx is not None and idx < len(r) else None
            if d and (latest is None or d > latest):
                latest = d
        return latest
    finally:
        wb.close()


def main():
    drive.MAX_DEPTH = 3
    with tempfile.TemporaryDirectory(prefix="cw-") as work:
        work = Path(work)
        found = {k: [] for k in ("consumable", "wastage", "sales", "zones", "targets")}
        kinds = set(found)
        for label, folder in (("data", FOLDER),):
            log(f"Listing {label} folder {folder}…")
            try:
                items = drive.walk(folder)
            except RuntimeError as err:
                log(f"::error::{err}")
                return 1
            for n, item in enumerate(items):
                if not (item["name"].lower().endswith(DATA_SUFFIXES) or item["mimeType"] == drive.GSHEET_MIME):
                    continue
                suffix = Path(item["name"]).suffix.lower() or ".xlsx"
                dest = work / f"{label[:2]}{n}{suffix}"
                try:
                    dest.write_bytes(drive.fetch_bytes(item))
                except RuntimeError as err:
                    log(f"::warning::{err}")
                    continue
                try:
                    kind = classify(dest)
                except Exception:  # noqa: BLE001 - unreadable file is simply not ours
                    kind = None
                if not kind or kind[0] not in kinds:
                    log(f"  skip  {item['path']}  (not a consumable/wastage layout)")
                    dest.unlink()
                    continue
                # Keep the Drive name (bd reports it on the Data quality page) inside a per-file folder.
                named = work / f"f{n}{label[:2]}" / item["name"]
                named.parent.mkdir()
                dest.rename(named)
                found[kind[0]].append((kind[1], drive.modified_sort_key(item), named, item["path"]))
                log(f"  found {item['path']}  →  {kind[0]}" + (f" (data to {kind[1]})" if kind[1] else ""))
        missing = [k for k, v in found.items() if not v]
        if missing:
            log(f"::error::No {', '.join(missing)} file recognised in the Drive folders.")
            return 1
        files = {}
        for kind, options in found.items():
            options.sort(key=lambda o: (o[0] or bd.dt.date.min, o[1]), reverse=True)
            if len(options) > 1:
                log(f"::warning::{len(options)} {kind} files found; using {options[0][3]}. Others: {', '.join(o[3] for o in options[1:])}")
            files[kind] = options[0][2]
        try:
            payload = bd.build_dashboard_data(work, files)
        except Exception as err:  # noqa: BLE001 - report and keep the last good file
            log(f"::error::Consumable & wastage build failed: {err}")
            return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(tmp, OUT)
    al = payload["dataQuality"].get("periodAlignment") or {}
    log(f"Wrote {OUT}: {len(payload['outlets'])} outlets, {len(payload['daily'])} outlet-days, "
        f"{payload['dateRange']['min']} to {payload['dateRange']['max']}.")
    if not al.get("aligned"):
        log(f"::warning::Source periods differ: " + ", ".join(f"{k} {v['dateMin']}–{v['dateMax']}" for k, v in (al.get("sources") or {}).items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
