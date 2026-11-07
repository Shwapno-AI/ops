"""Structural validation of a plan before anything runs."""

from __future__ import annotations

import re

import pandas as pd

from .engine import AGGREGATIONS, RunResult
from .errors import PlanError
from .expr import resolve_column
from .normalize import is_missing, key_norm
from .reader import SERIAL_NAME, key_column

REQUIRED_STEP_KEYS = {
    "rename": ["map"],
    "select": ["columns"],
    "drop": ["columns"],
    "filter": ["column", "test"],
    "derive": ["column", "expr"],
    "join": ["with", "on"],
    "group": ["by", "aggs"],
    "pivot": ["index", "columns", "values"],
    "unpivot": ["id_columns", "value_columns"],
    "sort": ["by"],
    "dedupe": [],
    "fill_down": ["columns"],
    "to_number": ["columns"],
    "to_text": ["columns"],
    "to_date": ["columns"],
    "limit": ["n"],
}
MAX_FRAMES = 60
MAX_STEPS = 60


def validate_plan(plan: dict, source_ids: set[str], template_sheets: dict | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["Plan must be a JSON object"]
    frames = plan.get("frames")
    if not isinstance(frames, list) or not frames:
        return ["'frames' must be a non-empty list"]
    if len(frames) > MAX_FRAMES:
        errors.append(f"Too many frames (max {MAX_FRAMES})")

    for override in plan.get("source_overrides") or []:
        if not isinstance(override, dict) or override.get("source") not in source_ids:
            errors.append(f"source_overrides: unknown source in {override}")
        elif not isinstance(override.get("header_row"), int) or override["header_row"] < 1:
            errors.append(f"source_overrides: header_row must be a positive integer in {override}")

    seen: set[str] = set()
    for spec in frames:
        if not isinstance(spec, dict) or not isinstance(spec.get("name"), str) or not spec["name"]:
            errors.append(f"Each frame needs a 'name': {str(spec)[:120]}")
            continue
        name = spec["name"]
        if name in seen or name in source_ids:
            errors.append(f"Frame name {name!r} is already used")
        origins = spec.get("from")
        if not isinstance(origins, list) or not origins:
            errors.append(f"Frame {name!r}: 'from' must be a non-empty list")
        else:
            for item in origins:
                source = item if isinstance(item, str) else item.get("source") if isinstance(item, dict) else None
                if source not in source_ids and source not in seen:
                    errors.append(f"Frame {name!r}: unknown source {source!r} (use a source id or an earlier frame)")
        steps = spec.get("steps", [])
        if not isinstance(steps, list) or len(steps) > MAX_STEPS:
            errors.append(f"Frame {name!r}: 'steps' must be a list of at most {MAX_STEPS}")
            steps = []
        for step in steps:
            op = step.get("op") if isinstance(step, dict) else None
            if op not in REQUIRED_STEP_KEYS:
                errors.append(f"Frame {name!r}: unknown op {op!r}; allowed: {sorted(REQUIRED_STEP_KEYS)}")
                continue
            for key in REQUIRED_STEP_KEYS[op]:
                if key not in step:
                    errors.append(f"Frame {name!r}, op {op!r}: missing {key!r}")
            if op == "join" and step.get("with") in [i if isinstance(i, str) else i.get("source") for i in (origins or []) if isinstance(i, (str, dict))]:
                errors.append(f"Frame {name!r}: {step['with']!r} is in both 'from' and a join. 'from' stacks rows, so list it only in the join.")
            if op == "group" and isinstance(step.get("aggs"), dict):
                for aggregation in step["aggs"].values():
                    if aggregation not in AGGREGATIONS:
                        errors.append(f"Frame {name!r}: aggregation {aggregation!r} not allowed")
        seen.add(name)

    if template_sheets is None:
        sheets = plan.get("sheets")
        if not isinstance(sheets, list) or not sheets:
            errors.append("'sheets' must be a non-empty list when there is no template")
        else:
            for sheet in sheets:
                if not isinstance(sheet, dict) or not sheet.get("name") or sheet.get("frame") not in seen:
                    errors.append(f"Sheet needs a name and a known frame: {str(sheet)[:150]}")
    else:
        mappings = plan.get("template") or []
        cells = plan.get("cells") or []
        if not mappings and not cells:
            errors.append("Template mode needs 'template' mappings or 'cells'")
        for mapping in mappings:
            errors.extend(_validate_mapping(mapping, template_sheets, seen))
        for cell in cells:
            if not isinstance(cell, dict) or cell.get("sheet") not in template_sheets:
                errors.append(f"cells: unknown sheet in {str(cell)[:150]}")
            elif not re.fullmatch(r"[A-Z]{1,3}[1-9]\d*", str(cell.get("cell", ""))):
                errors.append(f"cells: bad cell reference in {cell}")
            elif "value" not in cell and not ({"frame", "column", "agg"} <= cell.keys() and cell["frame"] in seen):
                errors.append(f"cells: need 'value', or 'frame'+'column'+'agg', in {cell}")
    return errors


def _validate_mapping(mapping: dict, template_sheets: dict, frames: set[str]) -> list[str]:
    errors: list[str] = []
    sheet_name = mapping.get("sheet") if isinstance(mapping, dict) else None
    sheet = template_sheets.get(sheet_name)
    if sheet is None:
        return [f"template: unknown sheet {sheet_name!r}; available: {list(template_sheets)}"]
    if mapping.get("frame") not in frames:
        errors.append(f"template[{sheet_name}]: unknown frame {mapping.get('frame')!r}")
    mode = mapping.get("mode")
    if mode not in ("append", "fill_by_key"):
        errors.append(f"template[{sheet_name}]: mode must be 'append' or 'fill_by_key'")
    columns = mapping.get("columns")
    if not isinstance(columns, dict) or not columns:
        return errors + [f"template[{sheet_name}]: 'columns' must map column letters to frame columns"]
    key = mapping.get("key") or {}
    if mode == "fill_by_key" and not key:
        errors.append(f"template[{sheet_name}]: fill_by_key needs 'key'")
    for letter in [*columns, *key]:
        column = sheet.columns.get(letter)
        if column is None:
            errors.append(f"template[{sheet_name}]: column {letter!r} is not in the template table; available: {list(sheet.columns)}")
        elif column.formula and letter in columns:
            errors.append(f"template[{sheet_name}]: column {letter} ({column.header}) has a formula; never map it")
    return errors


def repeated_records(frame: pd.DataFrame) -> tuple[str, list, bool] | None:
    """The same key repeating with identical numbers means the same record was counted twice.

    Returns (key column, the repeating key values, whether it is widespread).
    """
    key = key_column(frame)
    if key is None:
        return None
    keys = frame[key].map(key_norm)
    repeats = frame[(keys != "") & keys.duplicated(keep=False)]
    columns = [c for c in frame.columns if c != key and pd.api.types.is_numeric_dtype(frame[c]) and not SERIAL_NAME.match(str(c))]
    if repeats.empty or not columns:
        return None
    grouped = repeats.assign(__key=keys[repeats.index]).groupby("__key")
    same = (grouped[columns].nunique(dropna=True) <= 1).all(axis=1)
    if not same.any():
        return None
    return key, same[same].index.tolist(), bool(same.mean() >= 0.8 and len(repeats) >= max(2, 0.1 * len(frame)))


def _check_repeats(plan: dict, result: RunResult, used_frames: list[str], errors: list[str]) -> None:
    specs = {spec["name"]: spec for spec in plan["frames"]}
    for name in dict.fromkeys(used_frames):
        found = repeated_records(result.frames[name])
        if not found:
            continue
        key, values, widespread = found
        if widespread and not specs[name].get("keep_repeats"):
            errors.append(
                f"Frame {name!r}: {len(values)} {key} values repeat on several rows with identical numbers, which double counts them. "
                f"Add a group step with 'by' holding {key} and its number columns, 'first' for names and 'concat_unique' for notes. "
                "Set \"keep_repeats\": true on the frame only if these really are separate records."
            )
        else:
            shown = ", ".join(str(v).upper() for v in values[:6])
            result.check("Repeated records", "warn", f"{len(values)} {key} values are on more than one row with the same numbers ({shown}), so totals may count them twice.")


def _check_filled(frame: pd.DataFrame, columns: list[str], label: str, errors: list[str]) -> None:
    for name in columns:
        column = resolve_column(frame, name)
        if frame[column].map(is_missing).all():
            errors.append(f"{label}: column {column!r} is completely empty in the frame, so nothing would be written. Check the join or filter that builds it.")


def validate_against_frames(plan: dict, result: RunResult, template_sheets: dict | None) -> list[str]:
    """Checks that need the computed frames: columns exist, keys match, data really arrives."""
    errors: list[str] = []
    try:
        used = [s["frame"] for s in plan.get("sheets") or []] if template_sheets is None else [m["frame"] for m in plan.get("template") or []]
        _check_repeats(plan, result, used, errors)
        if template_sheets is None:
            for sheet in plan["sheets"]:
                frame = result.frames[sheet["frame"]]
                if frame.empty:
                    errors.append(f"Sheet {sheet['name']!r}: frame is empty")
                for column in [*(sheet.get("total_columns") or []), *(sheet.get("formats") or {})]:
                    resolve_column(frame, column)
            return errors
        for mapping in plan.get("template") or []:
            frame = result.frames[mapping["frame"]]
            label = f"template[{mapping['sheet']}]"
            if frame.empty:
                errors.append(f"{label}: frame is empty")
                continue
            _check_filled(frame, list(mapping["columns"].values()), label, errors)
            if mapping["mode"] == "fill_by_key":
                names = [resolve_column(frame, c) for c in mapping["key"].values()]
                keys = frame[names].astype(object).apply(lambda r: tuple(key_norm(v) for v in r), axis=1)
                repeated = keys[keys.duplicated()]
                if len(repeated):
                    errors.append(f"{label}: key is not unique in frame ({len(repeated)} repeats, e.g. {repeated.iloc[0]}); add a 'group' step first")
                sheet = template_sheets[mapping["sheet"]]
                present = {tuple(k) for k in sheet.key_tuples(list(mapping["key"]))}
                if not present:
                    errors.append(f"{label}: the template has no keys listed in column(s) {list(mapping['key'])}, so fill_by_key has nothing to fill. Use mode 'append'.")
                elif not present & set(keys):
                    errors.append(f"{label}: no template key matches the frame. Template keys like {list(present)[:3]}, frame keys like {keys.head(3).tolist()}")
        for cell in plan.get("cells") or []:
            if "frame" in cell:
                resolve_column(result.frames[cell["frame"]], cell["column"])
    except PlanError as exc:
        errors.append(str(exc))
    return errors
