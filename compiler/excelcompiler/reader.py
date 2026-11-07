"""Read any spreadsheet into clean tables: finds the header, drops totals, types columns."""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from lxml import html
from openpyxl.utils import get_column_letter
from python_calamine import CalamineWorkbook, SheetTypeEnum, SheetVisibleEnum

from .errors import CompileError
from .normalize import coerce_column, is_missing, key_norm, norm_label, parse_number, total_label_in_row

SPREADSHEET_EXTENSIONS = {".xlsx", ".xlsm", ".xlsb", ".xls", ".ods", ".csv", ".tsv", ".txt"}
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"
HEADER_SCAN_ROWS = 40


@dataclass
class RawSheet:
    file: str
    name: str
    rows: list[list]
    hidden: bool = False


@dataclass
class Table:
    id: str
    file: str
    sheet: str
    hidden: bool
    header_row: int  # 1-based row of the lowest header line
    header_depth: int
    df: pd.DataFrame
    above_header: list[list] = field(default_factory=list)
    dropped_labels: list[str] = field(default_factory=list)
    repeated_headers: int = 0
    footer_rows: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def signature(self) -> tuple:
        return tuple(norm_label(c) for c in self.df.columns)


def list_input_files(folder: Path) -> tuple[list[Path], list[str]]:
    files, ignored = [], []
    if not folder.exists():
        return files, ignored
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if path.name.startswith((".", "~$")):
            continue
        (files if path.suffix.lower() in SPREADSHEET_EXTENSIONS else ignored).append(path)
    return files, [p.name for p in ignored]


def _clean_cell(value):
    if isinstance(value, str):
        value = value.replace("\xa0", " ").strip()
        return value or None
    return value


def _read_excel(path: Path) -> list[RawSheet]:
    try:
        workbook = CalamineWorkbook.from_path(str(path))
    except Exception as exc:
        with open(path, "rb") as handle:
            ole = handle.read(8) == _OLE_MAGIC
        if ole and path.suffix.lower() in {".xlsx", ".xlsm", ".xlsb"}:
            raise CompileError(f"{path.name} is password protected. Remove the password and upload it again.") from exc
        raise CompileError(f"{path.name} could not be read ({exc}).") from exc
    sheets = []
    for meta in workbook.sheets_metadata:
        if meta.typ != SheetTypeEnum.WorkSheet:
            continue
        rows = workbook.get_sheet_by_name(meta.name).to_python(skip_empty_area=False)
        cleaned = [[_clean_cell(c) for c in row] for row in rows]
        sheets.append(RawSheet(path.name, meta.name, cleaned, meta.visible != SheetVisibleEnum.Visible))
    return sheets


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if data[:3] == b"\xef\xbb\xbf":
        return data.decode("utf-8-sig")
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _html_tables(text: str) -> list[list[list]]:
    """Read HTML tables as text, cell by cell, so codes such as 00123 keep their zeros."""
    tables = []
    for table in html.fromstring(text).iter("table"):
        rows: list[list] = []
        spans: dict[int, int] = {}
        for tr in table.iter("tr"):
            row: list = []
            for cell in tr:
                if cell.tag not in ("td", "th"):
                    continue
                while spans.get(len(row), 0) > 0:
                    spans[len(row)] -= 1
                    row.append(None)
                colspan = int(cell.get("colspan", 1) or 1)
                rowspan = int(cell.get("rowspan", 1) or 1)
                row.append(_clean_cell(cell.text_content()))
                row.extend([None] * (colspan - 1))
                if rowspan > 1:
                    for j in range(len(row) - colspan, len(row)):
                        spans[j] = rowspan - 1
            rows.append(row)
        if any(any(c is not None for c in row) for row in rows):
            tables.append(rows)
    return tables


def _read_text(path: Path) -> list[RawSheet]:
    """Handles CSV/TSV and the fake .xls files SAP and others export (text or HTML inside)."""
    text = _decode(path.read_bytes())
    if "<table" in text[:65536].casefold():
        return [RawSheet(path.name, f"Table{i}", rows) for i, rows in enumerate(_html_tables(text), 1)]
    sample = [line for line in text.splitlines()[:50] if line.strip()]
    if not sample:
        return [RawSheet(path.name, path.stem, [])]
    delimiter = max("\t,;|", key=lambda d: sorted(line.count(d) for line in sample)[len(sample) // 2])
    rows = [[_clean_cell(c) for c in row] for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]
    return [RawSheet(path.name, path.stem, rows)]


def read_file(path: Path) -> list[RawSheet]:
    with open(path, "rb") as handle:
        head = handle.read(8)
    if head.startswith(_ZIP_MAGIC) or head == _OLE_MAGIC:
        return _read_excel(path)
    return _read_text(path)


def _header_text(value) -> str | None:
    if is_missing(value):
        return None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%b-%y") if value.day == 1 else value.isoformat()[:10]
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_text_cell(value) -> bool:
    if isinstance(value, (dt.datetime, dt.date)):
        return True
    return isinstance(value, str) and parse_number(value) is None


def detect_header(rows: list[list]) -> tuple[int, int] | None:
    """Return (0-based header row, depth). Later rows must score clearly higher to win."""
    best_score, best_row = 0.0, None
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [(j, c) for j, c in enumerate(row) if c is not None]
        if not cells:
            continue
        texts = [c for _, c in cells if _is_text_cell(c)]
        if not texts:
            continue
        below = rows[i + 1 : i + 6]
        widest = max((sum(c is not None for c in r) for r in below), default=0)
        positions = {j for j, _ in cells}
        covered = {j for r in below for j, c in enumerate(r) if c is not None}
        align = len(positions & covered) / len(positions)
        unique = len({norm_label(t) for t in texts}) / len(texts)
        width_fit = 0.5 + 0.5 * min(1.0, len(cells) / widest) if widest else 1.0
        text_share = len(texts) / len(cells)
        score = len(cells) * text_share * text_share * (0.5 + 0.5 * unique) * (0.3 + 0.7 * align) * width_fit
        if score > best_score * 1.10:
            best_score, best_row = score, i
    if best_row is None:
        return None
    labels = [_header_text(c) for c in rows[best_row] if c is not None]
    normalised = [norm_label(l) for l in labels]
    depth = 1
    if best_row > 0 and len(set(normalised)) < len(normalised):
        above = [c for c in rows[best_row - 1] if c is not None]
        if len(above) >= 2 and all(isinstance(c, (str, dt.date, dt.datetime)) for c in above):
            depth = 2
    return best_row, depth


def flatten_header(block: list[list], width: int) -> list[str | None]:
    """Join stacked header lines; a group label spans until the next one appears."""
    filled: list[list[str | None]] = []
    for level, row in enumerate(block):
        texts = [_header_text(row[j]) if j < len(row) else None for j in range(width)]
        if level < len(block) - 1:
            current = None
            for j, text in enumerate(texts):
                current = text if text is not None else current
                texts[j] = current
        filled.append(texts)
    headers = []
    for j in range(width):
        parts: list[str] = []
        for line in filled:
            if line[j] is not None and line[j] not in parts:
                parts.append(line[j])
        headers.append(" | ".join(parts) if parts else None)
    return headers


def _unique_columns(headers: list[str | None]) -> list[str]:
    seen: dict[str, int] = {}
    columns = []
    for j, header in enumerate(headers):
        name = header or f"Column {get_column_letter(j + 1)}"
        key = norm_label(name)
        seen[key] = seen.get(key, 0) + 1
        columns.append(name if seen[key] == 1 else f"{name} ({seen[key]})")
    return columns


def _is_noise(row: list) -> bool:
    cells = [c for c in row if c is not None]
    return bool(cells) and all(isinstance(c, str) and re.fullmatch(r"[-=_*.\s]+", c) for c in cells)


def _sub_header(body: list[list], width: int) -> tuple[int, dict[int, str]] | None:
    """A line right under the header that labels columns instead of holding data."""
    first = next((i for i, row in enumerate(body[:2]) if any(c is not None for c in row)), None)
    if first is None:
        return None
    row = body[first]
    cells = {j: c for j, c in enumerate(row) if c is not None}
    if not all(_is_text_cell(c) for c in cells.values()):
        return None
    sample = [r for r in body[first + 1 : first + 31] if any(c is not None for c in r)]
    if len(sample) < 2:
        return None

    def number_share(j: int) -> float:
        values = [r[j] for r in sample if r[j] is not None]
        return sum(parse_number(v) is not None for v in values) / len(values) if values else 0.0

    def fill(j: int) -> float:
        return sum(r[j] is not None for r in sample) / len(sample)

    identifiers = [j for j in range(width) if fill(j) >= 0.7 and number_share(j) < 0.3]
    if not identifiers or row[identifiers[0]] is not None:
        return None
    if not any(number_share(j) >= 0.7 or fill(j) < 0.7 for j in cells):
        return None
    return first, {j: str(c).strip() for j, c in cells.items()}


def _group_labels(rows: list[list], index: int, headers: list[str | None]) -> list[str | None]:
    """Repeated headers under group titles, even with a line of counts in between."""
    counts = Counter(norm_label(h) for h in headers if h)
    if not any(count > 1 for count in counts.values()):
        return headers
    for above in range(index - 1, max(index - 3, -1), -1):
        titles = {j: c for j, c in enumerate(rows[above]) if isinstance(c, str) and parse_number(c) is None}
        if len(titles) < 2:
            continue
        named = list(headers)
        for j, header in enumerate(headers):
            if header and counts[norm_label(header)] > 1:
                owner = max((t for t in titles if t <= j), default=None)
                if owner is not None:
                    named[j] = f"{titles[owner].strip()} | {header}"
        return named
    return headers


def _is_sum_row(row: list, above: list[list]) -> bool:
    """A last row whose numbers equal the sum of everything above it, labelled or not."""
    if len(above) < 2:
        return False
    numbers = [(j, parse_number(c)) for j, c in enumerate(row) if parse_number(c) not in (None, 0.0)]
    text_cells = sum(1 for c in row if c is not None and parse_number(c) is None)
    if not numbers or text_cells > 1:
        return False
    matched = 0
    for j, value in numbers:
        total = sum(parse_number(r[j]) or 0.0 for r in above)
        if abs(total - value) <= max(1e-6, abs(value) * 1e-6):
            matched += 1
    return matched >= (1 if text_cells == 0 else 2)


def build_table(raw: RawSheet, table_id: str, header_row: int | None = None, depth: int | None = None) -> Table | None:
    """Turn one raw sheet into a Table. header_row is 1-based when given by a plan."""
    rows = raw.rows
    if not any(any(c is not None for c in row) for row in rows):
        return None
    if header_row is None:
        found = detect_header(rows)
        if found is None:
            return None
        index, level = found
        depth = depth or level
    else:
        index = header_row - 1
        if not 0 <= index < len(rows):
            raise ValueError(f"header_row {header_row} is outside {raw.name} ({len(rows)} rows)")
        depth = depth or 1

    width = max(len(r) for r in rows)
    top = max(0, index - depth + 1)
    headers = flatten_header(rows[top : index + 1], width)
    if depth == 1:
        headers = _group_labels(rows, index, headers)
    body = [r + [None] * (width - len(r)) for r in rows[index + 1 :]]

    sub_header = _sub_header(body, width)
    if sub_header:
        first, labels = sub_header
        body = body[first + 1 :]
        seen: set[str] = set()
        for j in range(width):
            label = labels.get(j)
            key = norm_label(headers[j]) if headers[j] else None
            if label and headers[j] is None:
                headers[j] = label
            elif label and key in seen:
                headers[j] = f"{headers[j]} | {label}"
            if key:
                seen.add(key)

    keep = [j for j in range(width) if headers[j] is not None or any(r[j] is not None for r in body)]
    if not keep:
        return None
    headers = [headers[j] for j in keep]
    body = [[r[j] for j in keep] for r in body]
    header_norm = [norm_label(h) if h else "" for h in headers]

    kept: list[list] = []
    dropped: list[str] = []
    repeated = 0
    for row in body:
        cells = [c for c in row if c is not None]
        if not cells or _is_noise(row):
            continue
        matches = sum(1 for c, h in zip(row, header_norm) if c is not None and h and norm_label(c) == h)
        if matches >= max(2, 0.8 * len(cells)):
            repeated += 1
            continue
        label = total_label_in_row(row)
        if label is not None:
            dropped.append(label)
            continue
        kept.append(row)

    footers = 0
    if len(headers) >= 4:
        while kept and sum(c is not None for c in kept[-1]) <= 1:
            kept.pop()
            footers += 1
    if kept and _is_sum_row(kept[-1], kept[:-1]):
        tail = kept.pop()
        dropped.append(next((str(c) for c in tail if isinstance(c, str) and parse_number(c) is None), "unlabelled total"))

    frame = pd.DataFrame(kept, columns=_unique_columns(headers), dtype=object)
    table = Table(
        id=table_id,
        file=raw.file,
        sheet=raw.name,
        hidden=raw.hidden,
        header_row=index + 1,
        header_depth=depth,
        df=frame,
        above_header=[[c for c in r if c is not None] for r in rows[:top] if any(c is not None for c in r)][:6],
        dropped_labels=dropped,
        repeated_headers=repeated,
        footer_rows=footers,
    )
    for column in list(frame.columns):
        converted, info = coerce_column(frame[column])
        frame[column] = converted
        if info["errors"]:
            table.notes.append(f"'{column}' has {info['errors']} Excel errors (#N/A, #REF! and similar)")
        if info["non_numeric"]:
            table.notes.append(f"'{column}' is mostly numbers, but also holds {info['non_numeric']}")
        if len(frame) and frame[column].isna().all():
            table.notes.append(f"'{column}' is completely empty")
    return table


KEY_NAME = re.compile(r"(^|[\W_])(code|id|sku|article|barcode)($|[\W_])", re.I)
SERIAL_NAME = re.compile(r"^(sl|s\.?\s*no\.?|sr\.?\s*no\.?|serial( no\.?)?|#)$", re.I)


def key_column(frame: pd.DataFrame, unique_share: float = 0.0) -> str | None:
    """The identifying column, judged by its name, such as Outlet Code or SKU."""
    for column in frame.columns:
        if not KEY_NAME.search(str(column)):
            continue
        filled = frame[column].dropna()
        if len(filled) and len(filled) >= 0.5 * len(frame) and filled.map(key_norm).nunique() >= unique_share * len(filled):
            return column
    return None


def _numbers_by_key(table: Table, key: str, columns: list[str]) -> dict[str, tuple]:
    lookup = {norm_label(c): c for c in table.df.columns}
    names = [lookup[c] for c in columns]
    result: dict[str, tuple] = {}
    for row in table.df[[key, *names]].itertuples(index=False, name=None):
        result.setdefault(key_norm(row[0]), tuple(None if is_missing(v) else parse_number(v) for v in row[1:]))
    return result


def key_overlap(tables: list[Table]) -> list[dict]:
    """Tell the planner when several tables list the same records, e.g. one list sent to everyone."""
    groups: dict[str, list[tuple[Table, str]]] = {}
    for table in tables:
        if table.hidden or not len(table.df):
            continue
        key = key_column(table.df, unique_share=0.8)
        if key:
            groups.setdefault(norm_label(key), []).append((table, key))
    findings = []
    for members in groups.values():
        if len(members) < 2:
            continue
        counts: Counter = Counter()
        for table, key in members:
            counts.update({key_norm(v) for v in table.df[key].dropna()})
        repeated = {k for k, count in counts.items() if count > 1 and k}
        if not repeated:
            continue
        shared = None
        for table, _ in members:
            names = {norm_label(c) for c in table.df.columns if pd.api.types.is_numeric_dtype(table.df[c]) or numeric_share(table.df[c]) >= 0.8}
            names = {n for n in names if not SERIAL_NAME.match(n)}
            shared = names if shared is None else shared & names
        finding = {"column": members[0][1], "tables": [t.id for t, _ in members], "distinct_keys": len(counts), "keys_in_2_or_more_tables": len(repeated)}
        if shared:
            columns = sorted(shared)
            books = [_numbers_by_key(t, k, columns) for t, k in members]
            same = 0
            for key_value in repeated:
                values = {b[key_value] for b in books if key_value in b}
                same += len(values) == 1
            finding["same_numbers_pct"] = round(100 * same / len(repeated))
        findings.append(finding)
    return findings


def numeric_share(series: pd.Series) -> float:
    values = series.dropna()
    return sum(parse_number(v) is not None for v in values) / len(values) if len(values) else 0.0


def profile_table(table: Table, sample_rows: int) -> dict:
    """What the AI sees: structure always; values only when sample_rows > 0."""
    frame = table.df
    if table.hidden:
        return {"id": table.id, "file": table.file, "sheet": table.sheet, "hidden": True, "rows": len(frame), "columns": [{"name": c} for c in frame.columns]}
    columns = []
    for name in frame.columns:
        series = frame[name]
        kind = "number" if pd.api.types.is_numeric_dtype(series) else "date" if pd.api.types.is_datetime64_any_dtype(series) else "text"
        filled = int(series.notna().sum())
        info = {"name": name, "type": kind, "filled_pct": round(100 * filled / len(frame)) if len(frame) else 0}
        if kind == "text" and filled:
            distinct = series.dropna().astype(str)
            info["unique"] = int(distinct.nunique())
            if sample_rows and info["unique"] <= 12:
                info["values"] = [v[:60] for v in sorted(distinct.unique().tolist())]
        columns.append(info)
    profile = {
        "id": table.id,
        "file": table.file,
        "sheet": table.sheet,
        "hidden": table.hidden,
        "header_row": table.header_row,
        "header_depth": table.header_depth,
        "rows": len(frame),
        "columns": columns,
    }
    if sample_rows:
        sample = frame.head(sample_rows).astype(object).where(frame.head(sample_rows).notna(), None)
        profile["sample_rows"] = [[_json_value(v) for v in row] for row in sample.values.tolist()]
        if table.above_header:
            profile["text_above_header"] = [[_json_value(v) for v in row] for row in table.above_header]
    return profile


def _json_value(value):
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return value.isoformat()[:10]
    if isinstance(value, str):
        return value[:80]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:80]
