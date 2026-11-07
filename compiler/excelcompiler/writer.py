"""Writes the no-template workbook and reads it back to prove the numbers arrived."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd
import xlsxwriter
from python_calamine import CalamineWorkbook

from .engine import RunResult, _sums_close
from .expr import resolve_column
from .normalize import is_missing, numeric

EXCEL_MAX_ROWS = 1_048_576
_CODE_NAME = re.compile(r"(^|[\s_])(code|id|no|number|sku|article|barcode|phone|mobile|year)($|[\s_.])", re.I)
FORMATS = {"integer": "#,##0", "decimal": "#,##0.00", "percent": "0.0%", "date": "yyyy-mm-dd", "text": "@", "code": "0"}


def safe_sheet_name(name: str, taken: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", str(name)).strip().strip("'")[:31] or "Sheet"
    candidate, counter = base, 2
    while candidate.casefold() in taken:
        suffix = f" {counter}"
        candidate, counter = base[: 31 - len(suffix)] + suffix, counter + 1
    taken.add(candidate.casefold())
    return candidate


def _column_kind(name: str, series: pd.Series, requested: str | None) -> str:
    if requested in FORMATS:
        return requested
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if not pd.api.types.is_numeric_dtype(series):
        return "text"
    values = series.dropna()
    if values.empty:
        return "decimal"
    whole = bool((values == values.round()).all())
    if whole and _CODE_NAME.search(name):
        return "code"
    if "%" in name and values.abs().max() <= 1.5:
        return "percent"
    return "integer" if whole else "decimal"


def _write_value(sheet, row: int, col: int, value, cell_format) -> None:
    if is_missing(value):
        sheet.write_blank(row, col, None, cell_format)
    elif isinstance(value, bool):
        sheet.write_boolean(row, col, value, cell_format)
    elif isinstance(value, (int, float)) or hasattr(value, "item"):
        sheet.write_number(row, col, float(value), cell_format)
    elif isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        sheet.write_datetime(row, col, value, cell_format)
    else:
        sheet.write_string(row, col, str(value)[:32767], cell_format)


def write_workbook(plan: dict, result: RunResult, path: Path) -> list[tuple]:
    """Returns (excel sheet, frame, rows, [first, last] frame position, has total) for read-back."""
    total_rows = sum(len(result.frames[s["frame"]]) for s in plan["sheets"])
    workbook = xlsxwriter.Workbook(
        str(path),
        {"constant_memory": total_rows > 200_000, "strings_to_numbers": False, "strings_to_formulas": False, "strings_to_urls": False},
    )
    header_format = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F3864", "border": 1, "border_color": "#FFFFFF", "text_wrap": True, "valign": "vcenter", "align": "center"})
    number_formats = {kind: workbook.add_format({"num_format": code}) for kind, code in FORMATS.items()}
    total_formats = {kind: workbook.add_format({"num_format": code, "bold": True, "top": 1, "bg_color": "#E7ECF4"}) for kind, code in FORMATS.items()}
    written, taken = [], set()

    for spec in plan["sheets"]:
        frame = result.frames[spec["frame"]]
        requested = {resolve_column(frame, k): v for k, v in (spec.get("formats") or {}).items()}
        totals = [resolve_column(frame, c) for c in spec.get("total_columns") or []]
        kinds = {c: _column_kind(str(c), frame[c], requested.get(c)) for c in frame.columns}
        limit = EXCEL_MAX_ROWS - 2
        parts = [frame.iloc[i : i + limit] for i in range(0, len(frame), limit)] or [frame]
        for part_no, part in enumerate(parts, 1):
            name = spec["name"] if len(parts) == 1 else f"{str(spec['name'])[:26]} {part_no}"
            sheet_name = safe_sheet_name(name, taken)
            sheet = workbook.add_worksheet(sheet_name)
            for j, column in enumerate(part.columns):
                sample = part[column].head(200).map(lambda v: "" if is_missing(v) else str(v)).map(len)
                width = max(int(sample.max()) if len(sample) else 0, min(len(str(column)), 24)) + 2
                sheet.set_column(j, j, min(max(width, 9), 45))
            sheet.set_row(0, 30)
            for j, column in enumerate(part.columns):
                sheet.write_string(0, j, str(column), header_format)
            sheet.freeze_panes(1, 0)
            for i, row in enumerate(part.itertuples(index=False, name=None), 1):
                for j, (value, column) in enumerate(zip(row, part.columns)):
                    _write_value(sheet, i, j, value, number_formats[kinds[column]])
            last = len(part)
            if last:
                sheet.autofilter(0, 0, last, len(part.columns) - 1)
            if totals and last:
                row = last + 1
                for j, column in enumerate(part.columns):
                    if column in totals:
                        letter = xlsxwriter.utility.xl_col_to_name(j)
                        sheet.write_formula(row, j, f"=SUBTOTAL(109,{letter}2:{letter}{last + 1})", total_formats[kinds[column]], float(numeric(part[column]).sum()))
                    elif j == 0:
                        sheet.write_string(row, j, "Total", total_formats["text"])
                    else:
                        sheet.write_blank(row, j, None, total_formats["text"])
            written.append((sheet_name, spec["frame"], len(part), list(part.index[[0, -1]]) if last else [0, 0], bool(totals and last)))
    workbook.close()
    return written


def verify_workbook(path: Path, written: list, result: RunResult) -> None:
    """Re-open the saved file and compare row counts and column totals with the frames."""
    book = CalamineWorkbook.from_path(str(path))
    for sheet_name, frame_name, rows, bounds, has_total in written:
        data = book.get_sheet_by_name(sheet_name).to_python(skip_empty_area=False)
        found = len(data) - 1 - (1 if has_total else 0)
        result.check(f"{sheet_name}: saved rows", "pass" if found == rows else "fail", f"expected {rows:,}, found {found:,}")
        if not rows:
            continue
        frame = result.frames[frame_name].iloc[bounds[0] : bounds[1] + 1]
        bad = []
        columns = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
        for column in columns:
            j = list(frame.columns).index(column)
            total = sum(float(r[j]) for r in data[1 : rows + 1] if isinstance(r[j], (int, float)) and not isinstance(r[j], bool))
            if not _sums_close(float(frame[column].sum()), total):
                bad.append(column)
        result.check(f"{sheet_name}: saved totals", "fail" if bad else "pass", f"do not match: {bad}" if bad else f"{len(columns)} number columns match")
