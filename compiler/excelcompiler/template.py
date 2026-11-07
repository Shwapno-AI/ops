"""Understands a user's template and fills it without touching its design or formulas."""

from __future__ import annotations

import copy
import datetime as dt
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries
from openpyxl.worksheet.cell_range import MultiCellRange
from python_calamine import CalamineWorkbook

from .engine import RunResult, _sums_close
from .errors import CompileError, PlanError
from .expr import resolve_column
from .normalize import ERROR_TOKENS, is_missing, is_total_label, key_norm, numeric
from .reader import _header_text, detect_header, flatten_header

EXCEL_MAX_ROWS = 1_048_576
SCAN_LIMIT = 200_000
_SUM_RANGE = re.compile(r"(?:SUM|SUBTOTAL|AVERAGE|COUNT|COUNTA|MAX|MIN)\(.*?\$?[A-Z]{1,3}\$?(\d+):\$?[A-Z]{1,3}\$?(\d+)", re.I)
_REF = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<sheet>(?:'[^']+'|[A-Za-z0-9_.]+)!)?"
    r"(?P<c1>\$?[A-Z]{1,3})(?P<d1>\$?)(?P<r1>\d+)"
    r"(?::(?P<c2>\$?[A-Z]{1,3})(?P<d2>\$?)(?P<r2>\d+))?(?![A-Za-z0-9_(])"
)


def _is_formula(value) -> bool:
    return (isinstance(value, str) and value.startswith("=")) or (value is not None and not isinstance(value, (str, int, float, bool, dt.date, dt.datetime, dt.time, dt.timedelta)))


@dataclass
class TemplateColumn:
    letter: str
    header: str
    formula: str | None = None
    formula_row: int | None = None
    values: dict[int, object] = field(default_factory=dict)


@dataclass
class TemplateSheet:
    name: str
    hidden: bool
    header_row: int | None = None
    header_top: int | None = None
    data_start: int | None = None
    last_data_row: int | None = None
    footer_row: int | None = None
    columns: dict[str, TemplateColumn] = field(default_factory=dict)
    suggested_key: str | None = None
    labels: list[dict] = field(default_factory=list)

    def key_tuples(self, letters: list[str]) -> list[tuple]:
        rows = sorted({r for l in letters for r in self.columns[l].values})
        keys = []
        for row in rows:
            cells = [self.columns[l].values.get(row) for l in letters]
            if not any(is_total_label(c) for c in cells):
                keys.append(tuple(key_norm(c) for c in cells))
        return keys

    def prompt_view(self, sample_rows: int) -> dict:
        view = {"sheet": self.name, "hidden": self.hidden, "header_row": self.header_row, "data_start_row": self.data_start, "last_data_row": self.last_data_row, "footer_row": self.footer_row, "suggested_mode": "fill_by_key" if self.suggested_key else "append", "suggested_key_column": self.suggested_key}
        columns = []
        for column in self.columns.values():
            entry = {"letter": column.letter, "header": column.header, "is_formula": bool(column.formula), "prefilled_rows": len(column.values)}
            if column.formula:
                entry["formula"] = column.formula
            if sample_rows and column.values:
                entry["samples"] = [str(v) for v in list(column.values.values())[:sample_rows]]
            columns.append(entry)
        view["columns"] = columns
        if sample_rows and not columns:
            view["labels"] = self.labels
        return view


@dataclass
class TemplateInfo:
    path: Path
    sheets: dict[str, TemplateSheet]
    warnings: list[str]

    def prompt_view(self, sample_rows: int) -> list[dict]:
        return [s.prompt_view(sample_rows) for s in self.sheets.values()]


def find_template(folder: Path) -> Path | None:
    if not folder or not folder.exists():
        return None
    files = [p for p in sorted(folder.iterdir()) if p.is_file() and not p.name.startswith((".", "~$"))]
    if len(files) > 1:
        raise CompileError(f"Use one template file; found {[p.name for p in files]}")
    return files[0] if files else None


def _convert_with_soffice(path: Path, folder: Path, target: str = "xlsx") -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise CompileError(f"{path.name}: this file type needs LibreOffice. Save it as .xlsx and try again.")
    profile = (folder / "lo_profile").resolve().as_uri()
    subprocess.run([soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore", "--convert-to", target, "--outdir", str(folder), str(path)], check=True, capture_output=True, timeout=300)
    converted = folder / f"{path.stem}.{target}"
    if not converted.exists():
        raise CompileError(f"{path.name} could not be converted. Save it as .xlsx and try again.")
    return converted


def prepare_template(path: Path, work_folder: Path) -> tuple[Path, list[str]]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return path, []
    if suffix in (".xls", ".xlsb", ".ods"):
        try:
            return _convert_with_soffice(path, work_folder), [f"Template {path.name} was converted to .xlsx first; compare its design with the original."]
        except (subprocess.SubprocessError, OSError) as exc:
            raise CompileError(f"{path.name} could not be converted ({type(exc).__name__}). Save it as .xlsx and try again.") from exc
    raise CompileError(f"{path.name}: a template must be .xlsx, .xlsm, .xls, .xlsb or .ods.")


def _fidelity_warnings(path: Path) -> list[str]:
    found = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    checks = {
        "xl/slicers/": "slicer",
        "xl/pivotTables/": "pivot table",
        "xl/ctrlProps/": "form control/button",
        "xl/charts/": "chart",
        "xl/diagrams/": "SmartArt",
    }
    for prefix, label in checks.items():
        if any(n.startswith(prefix) for n in names):
            found.append(label)
    shapes = False
    with zipfile.ZipFile(path) as archive:
        for name in names:
            if re.fullmatch(r"xl/drawings/drawing\d+\.xml", name) and b"<xdr:sp" in archive.read(name):
                shapes = True
                break
    if shapes:
        found.append("shape/text box")
    if not found:
        return []
    return [f"The template has {', '.join(found)}. These may not survive fully, so open the result and compare."]


def analyze_template(path: Path) -> TemplateInfo:
    try:
        book = load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
    except Exception as exc:
        raise CompileError(f"{path.name} could not be opened as a template ({exc}). If it has a password, remove it.") from exc
    sheets = {}
    for ws in book.worksheets:
        sheets[ws.title] = _analyze_sheet(ws)
    book.close()
    return TemplateInfo(path, sheets, _fidelity_warnings(path))


def _analyze_sheet(ws) -> TemplateSheet:
    sheet = TemplateSheet(name=ws.title, hidden=ws.sheet_state != "visible")
    max_row = min(ws.max_row, SCAN_LIMIT)
    max_col = ws.max_column
    grid = [list(row) for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col, values_only=True)]
    labels = []
    for r, row in enumerate(grid[:60], 1):
        for c, value in enumerate(row, 1):
            if value is not None and not _is_formula(value) and len(labels) < 80:
                labels.append({"cell": f"{get_column_letter(c)}{r}", "text": str(value)[:60]})
    sheet.labels = labels

    scan = [[0.0 if _is_formula(v) else (v.strip() or None if isinstance(v, str) else v) for v in row] for row in grid]
    found = detect_header(scan)
    if found is None or sum(c is not None for c in scan[found[0]]) < 2:
        return sheet
    index, depth = found
    merged_above = [m for m in ws.merged_cells.ranges if m.min_row == index and m.max_col > m.min_col]
    if depth == 1 and index > 0 and merged_above:
        span = max(m.size["columns"] for m in merged_above)
        width = sum(c is not None for c in scan[index])
        if span < 0.8 * max(width, 1):
            depth = 2
    top = index - depth + 1
    block = [list(r) for r in grid[top : index + 1]]
    for merged in ws.merged_cells.ranges:
        if merged.min_row - 1 <= index and merged.max_row - 1 >= top:
            value = grid[merged.min_row - 1][merged.min_col - 1]
            for r in range(max(merged.min_row - 1, top), min(merged.max_row - 1, index) + 1):
                for c in range(merged.min_col - 1, merged.max_col):
                    block[r - top][c] = value
    headers = flatten_header(block, max_col)

    sheet.header_row = index + 1
    sheet.header_top = top + 1
    sheet.data_start = index + 2

    in_table = [j for j in range(max_col) if headers[j] is not None]
    if not in_table:
        return sheet
    first_row = sheet.data_start
    while len(grid) < first_row:
        grid.append([None] * max_col)
    max_row = max(max_row, first_row)
    footer = None
    for r in range(first_row, max_row + 1):
        row = grid[r - 1]
        if any(is_total_label(row[j]) for j in in_table[:6]):
            footer = r
            break
        for j in in_table:
            value = row[j]
            if isinstance(value, str) and value.startswith("="):
                match = _SUM_RANGE.search(value)
                if match and first_row <= int(match.group(1)) and int(match.group(2)) < r:
                    footer = r
                    break
        if footer:
            break
    sheet.footer_row = footer
    if footer:
        last = footer - 1
    else:
        last = first_row
        for r in range(max_row, first_row - 1, -1):
            if any(grid[r - 1][j] is not None for j in in_table):
                last = r
                break
    sheet.last_data_row = last if footer else max(last, first_row)

    for j in in_table:
        letter = get_column_letter(j + 1)
        column = TemplateColumn(letter, headers[j])
        for r in range(first_row, sheet.last_data_row + 1):
            value = grid[r - 1][j]
            if value is None:
                continue
            if _is_formula(value):
                if column.formula is None:
                    column.formula = value if isinstance(value, str) else None
                    column.formula_row = r
                    if column.formula is None:
                        column.formula = "{array formula}"
            else:
                column.values[r] = value
        sheet.columns[letter] = column

    for letter, column in sheet.columns.items():
        if column.formula:
            continue
        distinct = {key_norm(v) for v in column.values.values() if not is_total_label(v)}
        if len(distinct) >= 3 and len(distinct) >= 0.9 * len(column.values):
            sheet.suggested_key = letter
        break
    return sheet


def _py_value(value):
    if is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value.item() if hasattr(value, "item") else value


def _set_value(cell, value) -> None:
    value = _py_value(value)
    cell.value = value
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"  # text from a source file must never become a live formula


def _rewrite_references(formula: str, current_sheet: str, target: str, sheet: TemplateSheet, new_end: int, delta: int) -> str:
    """Stretch ranges over the data block and move references below it after a footer shift."""
    start, old_end, top, footer = sheet.data_start, sheet.last_data_row, sheet.header_top, sheet.footer_row

    def update(match: re.Match) -> str:
        prefix = match.group("sheet")
        name = prefix[:-1].strip("'") if prefix else current_sheet
        if name != target:
            return match.group(0)
        r1 = int(match.group("r1"))
        text = f"{prefix or ''}{match.group('c1')}{match.group('d1')}"
        if match.group("r2") is None:
            if footer and r1 >= footer:
                r1 += delta
            return f"{text}{r1}"
        r2 = int(match.group("r2"))
        if top <= r1 <= start and old_end <= r2 < new_end and (not footer or r2 < footer):
            r2 = new_end
        elif footer and r1 >= footer:
            r1, r2 = r1 + delta, r2 + delta
        elif footer and r2 >= footer:
            r2 += delta
        return f"{text}{r1}:{match.group('c2')}{match.group('d2')}{r2}"

    return _REF.sub(update, formula)


def _extend_range_text(text: str, sheet: TemplateSheet, new_end: int) -> str:
    parts = []
    for piece in str(text).split():
        min_col, min_row, max_col, max_row = range_boundaries(piece)
        if None not in (min_col, min_row, max_col, max_row) and min_row <= sheet.data_start <= max_row < new_end:
            piece = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_end}"
        parts.append(piece)
    return " ".join(parts)


def _stretch_sheet_objects(ws, sheet: TemplateSheet, new_end: int) -> None:
    old_rules = ws.conditional_formatting
    new_rules = ConditionalFormattingList()
    for entry in old_rules:
        target = _extend_range_text(entry.sqref, sheet, new_end)
        for rule in entry.rules:
            new_rules.add(target, rule)
    ws.conditional_formatting = new_rules
    for validation in ws.data_validations.dataValidation:
        validation.sqref = MultiCellRange(_extend_range_text(validation.sqref, sheet, new_end))
    if ws.auto_filter.ref:
        min_col, min_row, max_col, max_row = range_boundaries(ws.auto_filter.ref)
        if min_row <= sheet.header_row and max_row < new_end:
            ws.auto_filter.ref = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_end}"
    for table in ws.tables.values():
        min_col, min_row, max_col, max_row = range_boundaries(table.ref)
        if min_row == sheet.header_row:
            extra = table.totalsRowCount or 0
            table.ref = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_end + extra}"
            if table.autoFilter is not None:
                table.autoFilter.ref = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_end}"


def _shift_footer(ws, sheet: TemplateSheet, delta: int) -> None:
    footer = sheet.footer_row
    last_row = ws.max_row
    merged = [m for m in list(ws.merged_cells.ranges) if m.min_row >= footer]
    bounds = [(m.min_col, m.min_row, m.max_col, m.max_row) for m in merged]
    for item in merged:
        ws.unmerge_cells(str(item))
    heights = {r: ws.row_dimensions[r].height for r in range(footer, last_row + 1) if r in ws.row_dimensions}
    ws.move_range(f"A{footer}:{get_column_letter(ws.max_column)}{last_row}", rows=delta, translate=False)
    for row in heights:
        ws.row_dimensions[row].height = None
    for row, height in heights.items():
        ws.row_dimensions[row + delta].height = height
    for c1, r1, c2, r2 in bounds:
        ws.merge_cells(start_row=r1 + delta, start_column=c1, end_row=r2 + delta, end_column=c2)


def _rewrite_workbook_formulas(book, target: str, sheet: TemplateSheet, new_end: int, delta: int) -> None:
    for ws in book.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("=") and cell.data_type == "f":
                    cell.value = _rewrite_references(cell.value, ws.title, target, sheet, new_end, delta)
    for name in book.defined_names.values():
        if name.attr_text:
            name.attr_text = _rewrite_references(name.attr_text, "", target, sheet, new_end, delta)


def _append(book, ws, sheet: TemplateSheet, mapping: dict, frame: pd.DataFrame, result: RunResult) -> dict:
    count = len(frame)
    start, old_end = sheet.data_start, sheet.last_data_row
    new_end = start + count - 1
    if new_end > EXCEL_MAX_ROWS:
        raise CompileError(f"{sheet.name}: {count:,} rows do not fit in one Excel sheet.")
    columns = {letter: resolve_column(frame, name) for letter, name in mapping["columns"].items()}
    formulas = {}
    for letter, column in sheet.columns.items():
        if column.formula and column.formula != "{array formula}":
            formulas[letter] = (column.formula, column.formula_row)

    delta = max(0, new_end - old_end) if sheet.footer_row else 0
    if new_end > old_end:
        if delta:
            _shift_footer(ws, sheet, delta)
            result.check(f"{sheet.name}: footer", "pass", f"Total row moved from {sheet.footer_row} to {sheet.footer_row + delta}")
        _rewrite_workbook_formulas(book, sheet.name, sheet, new_end, delta)
        formulas = {l: (_rewrite_references(f, sheet.name, sheet.name, sheet, new_end, delta), r) for l, (f, r) in formulas.items()}
        _stretch_sheet_objects(ws, sheet, new_end)

    styles = {letter: copy.copy(ws[f"{letter}{start}"]._style) for letter in sheet.columns}
    height = ws.row_dimensions[start].height if start in ws.row_dimensions else None
    indexes = {letter: column_index_from_string(letter) for letter in sheet.columns}
    arrays = {letter: frame[name].to_numpy(dtype=object) for letter, name in columns.items()}

    for offset in range(count):
        row = start + offset
        new_row = row > old_end
        if new_row and height is not None:
            ws.row_dimensions[row].height = height
        for letter in sheet.columns:
            cell = ws.cell(row=row, column=indexes[letter])
            if new_row:
                cell._style = copy.copy(styles[letter])
            if letter in arrays:
                _set_value(cell, arrays[letter][offset])
            elif letter in formulas:
                formula, origin = formulas[letter]
                cell.value = formula if row == origin else Translator(formula, origin=f"{letter}{origin}").translate_formula(f"{letter}{row}")
            elif not new_row:
                cell.value = None
    for row in range(new_end + 1, old_end + 1):
        for letter in sheet.columns:
            ws.cell(row=row, column=indexes[letter]).value = None
    if count < old_end - start + 1:
        result.check(f"{sheet.name}: spare rows", "warn", f"The template has room for {old_end - start + 1} rows and the data has {count}; the rest were left blank")
    return {"mode": "append", "first": start, "last": new_end, "expected": {letter: float(numeric(frame[name]).sum()) for letter, name in columns.items() if pd.api.types.is_numeric_dtype(frame[name])}, "rows": count}


def _fill(ws, sheet: TemplateSheet, mapping: dict, frame: pd.DataFrame, result: RunResult) -> dict:
    letters = list(mapping["key"])
    key_columns = [resolve_column(frame, mapping["key"][l]) for l in letters]
    columns = {letter: resolve_column(frame, name) for letter, name in mapping["columns"].items() if letter not in letters}
    keys = frame[key_columns].astype(object).apply(lambda r: tuple(key_norm(v) for v in r), axis=1)
    positions = {key: i for i, key in enumerate(keys)}
    used: set[tuple] = set()
    missing: list[str] = []
    expected = {letter: 0.0 for letter, name in columns.items() if pd.api.types.is_numeric_dtype(frame[name])}
    first, last = None, None
    blank_run, after_total = 0, False
    for row in range(sheet.data_start, ws.max_row + 1):
        cells = [ws[f"{l}{row}"].value for l in letters]
        if all(is_missing(c) for c in cells):
            blank_run += 1
            if blank_run >= 2 or after_total:
                break
            continue
        blank_run = 0
        after_total = any(is_total_label(c) for c in cells)
        if after_total or any(_is_formula(c) for c in cells):
            continue
        key = tuple(key_norm(c) for c in cells)
        position = positions.get(key)
        if position is None:
            missing.append(" / ".join(str(c) for c in cells))
        else:
            used.add(key)
        first = first or row
        last = row
        for letter, name in columns.items():
            cell = ws[f"{letter}{row}"]
            if _is_formula(cell.value):
                continue
            _set_value(cell, None if position is None else frame[name].iat[position])
            if position is not None and letter in expected:
                value = numeric(frame[name]).iat[position]
                expected[letter] += 0.0 if pd.isna(value) else float(value)
    left_out = [key for key in positions if key not in used and any(key)]
    if missing:
        result.check(f"{sheet.name}: key", "warn", f"{len(missing)} template rows have no data and were left blank (for example {missing[:5]})")
    if left_out:
        result.check(f"{sheet.name}: key", "warn", f"{len(left_out)} records are not listed in the template, so they were left out (for example {[' / '.join(k) for k in left_out[:5]]})")
    if not missing and not left_out:
        result.check(f"{sheet.name}: key", "pass", f"All {len(used)} rows matched")
    return {"mode": "fill_by_key", "first": first, "last": last, "expected": expected, "rows": len(used)}


def _cell_value(spec: dict, result: RunResult):
    if "value" in spec:
        return spec["value"]
    frame = result.frames[spec["frame"]]
    series = frame[resolve_column(frame, spec["column"])]
    aggregation = spec["agg"]
    if aggregation == "count":
        return int(series.notna().sum())
    if aggregation == "nunique":
        return int(series.nunique())
    if aggregation not in ("sum", "mean", "min", "max"):
        raise PlanError(f"cells: aggregation {aggregation!r} not allowed")
    return getattr(numeric(series), aggregation)()


def fill_template(info: TemplateInfo, plan: dict, result: RunResult, out_path: Path) -> list[dict]:
    book = load_workbook(info.path, keep_vba=info.path.suffix.lower() == ".xlsm")
    audit = []
    for mapping in plan.get("template") or []:
        sheet = info.sheets[mapping["sheet"]]
        ws = book[mapping["sheet"]]
        frame = result.frames[mapping["frame"]]
        details = _append(book, ws, sheet, mapping, frame, result) if mapping["mode"] == "append" else _fill(ws, sheet, mapping, frame, result)
        details["sheet"] = mapping["sheet"]
        audit.append(details)
        blanks = [f"{c.letter} ({c.header})" for l, c in sheet.columns.items() if not c.formula and l not in mapping["columns"] and l not in (mapping.get("key") or {})]
        if blanks:
            result.check(f"{sheet.name}: empty columns", "warn", f"No data was found for: {blanks}")
        mapped = {resolve_column(frame, n) for n in [*mapping["columns"].values(), *(mapping.get("key") or {}).values()]}
        unused = [c for c in frame.columns if c not in mapped]
        if unused:
            result.check(f"{sheet.name}: unused columns", "warn", f"In the data but not in the template: {unused[:15]}")
    for spec in plan.get("cells") or []:
        _set_value(book[spec["sheet"]][spec["cell"]], _cell_value(spec, result))
    book.calculation.fullCalcOnLoad = True
    book.save(out_path)
    book.close()
    return audit


def verify_template(out_path: Path, audit: list[dict], result: RunResult) -> None:
    """Reload the saved template and compare what landed in each mapped column."""
    book = load_workbook(out_path, read_only=True, data_only=False)
    for item in audit:
        ws = book[item["sheet"]]
        if item["first"] is None or not item["rows"]:
            result.check(f"{item['sheet']}: rows written", "fail", "No data was written to this sheet")
            continue
        wrong = []
        for letter, expected in item["expected"].items():
            index = column_index_from_string(letter)
            total = 0.0
            for row in ws.iter_rows(min_row=item["first"], max_row=item["last"], min_col=index, max_col=index, values_only=True):
                if isinstance(row[0], (int, float)) and not isinstance(row[0], bool):
                    total += float(row[0])
            if not _sums_close(expected, total):
                wrong.append(f"{letter}: expected {expected}, found {total}")
        result.check(f"{item['sheet']}: saved totals", "fail" if wrong else "pass", "; ".join(wrong) if wrong else f"{item['rows']:,} rows written, {len(item['expected'])} number columns match")
    book.close()


def recalculation_check(out_path: Path, result: RunResult) -> None:
    """Recalculate a throwaway copy in LibreOffice and look for formula errors."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        result.check("Formula check", "warn", "LibreOffice is not installed, so formulas were not checked")
        return
    with tempfile.TemporaryDirectory() as folder:
        try:
            converted = _convert_with_soffice(out_path, Path(folder))
            book = CalamineWorkbook.from_path(str(converted))
        except Exception as exc:
            result.check("Formula check", "warn", f"Could not check formulas: {type(exc).__name__}")
            return
        problems = []
        total = 0
        for name in book.sheet_names:
            for r, row in enumerate(book.get_sheet_by_name(name).to_python(skip_empty_area=False), 1):
                for c, value in enumerate(row, 1):
                    if isinstance(value, str) and value.strip().casefold() in ERROR_TOKENS:
                        total += 1
                        if len(problems) < 10:
                            problems.append(f"{name}!{get_column_letter(c)}{r} = {value}")
        if total:
            result.check("Formula check", "warn", f"{total} cells show an error, for example {problems}")
        else:
            result.check("Formula check", "pass", "No formula errors")
