"""A plan made without AI: used when no Qwen key is set and there is no instruction."""

from __future__ import annotations

import difflib

from .errors import CompileError
from .normalize import key_norm, norm_label
from .reader import Table


def _usable(tables: dict[str, Table]) -> list[Table]:
    return [t for t in tables.values() if not t.hidden and len(t.df)]


def auto_plan(tables: dict[str, Table]) -> dict:
    groups: list[list[Table]] = []
    for table in _usable(tables):
        names = set(table.signature)
        for group in groups:
            other = set(group[0].signature)
            if len(names & other) / max(len(names | other), 1) >= 0.8:
                group.append(table)
                break
        else:
            groups.append([table])
    if not groups:
        raise CompileError("No readable table was found in the files.")
    frames, sheets = [], []
    for index, group in enumerate(groups, 1):
        name = f"frame{index}"
        frames.append({"name": name, "from": [t.id for t in group], "add_source_columns": True, "keep_repeats": True})
        sheets.append({"name": "Compiled" if len(groups) == 1 else f"Compiled {index}", "frame": name})
    return {
        "summary": "Tables with the same structure were stacked into a master sheet (without AI).",
        "assumptions": [],
        "frames": frames,
        "sheets": sheets,
    }


def _best_match(header: str, names: list[str]) -> str | None:
    target = norm_label(header)
    lookup = {norm_label(n): n for n in names}
    if target in lookup:
        return lookup[target]
    close = difflib.get_close_matches(target, list(lookup), n=1, cutoff=0.85)
    return lookup[close[0]] if close else None


def template_plan(tables: dict[str, Table], sheets: dict) -> dict:
    frames, mappings = [], []
    usable = _usable(tables)
    for sheet in sheets.values():
        if sheet.hidden or not sheet.columns:
            continue
        open_columns = {l: c for l, c in sheet.columns.items() if not c.formula}
        scored = []
        for table in usable:
            names = list(table.df.columns)
            matches = {l: _best_match(c.header, names) for l, c in open_columns.items()}
            matches = {l: m for l, m in matches.items() if m}
            if len(matches) >= 2 or (len(matches) == 1 and len(open_columns) == 1):
                scored.append((len(matches), table, matches))
        if not scored:
            continue
        top = max(item[0] for item in scored)
        chosen = [item for item in scored if item[0] >= max(2 if len(open_columns) > 1 else 1, 0.5 * top)]
        name = f"frame_{len(frames) + 1}"
        origins = []
        for _, table, matches in chosen:
            rename = {m: open_columns[l].header for l, m in matches.items() if m != open_columns[l].header}
            origins.append({"source": table.id, "rename": rename})
        letters = sorted({l for _, _, matches in chosen for l in matches}, key=lambda l: (len(l), l))
        columns = {l: open_columns[l].header for l in letters}
        spec = {"name": name, "from": origins, "steps": [], "keep_repeats": True}
        mapping = {"sheet": sheet.name, "frame": name, "mode": "append", "columns": columns}

        key_letter = next((l for l in letters if sheet.suggested_key == l), None)
        if key_letter:
            mapping["mode"] = "fill_by_key"
            mapping["key"] = {key_letter: columns[key_letter]}
            mapping["columns"] = {l: c for l, c in columns.items() if l != key_letter}
            if mapping["columns"]:
                seen_keys = []
                for _, table, matches in chosen:
                    if key_letter in matches:
                        seen_keys.extend(key_norm(v) for v in table.df[matches[key_letter]])
                if len(set(seen_keys)) < len(seen_keys):
                    numeric_targets = set()
                    for _, table, matches in chosen:
                        for l, m in matches.items():
                            if l != key_letter and str(table.df[m].dtype) != "object":
                                numeric_targets.add(columns[l])
                    spec["steps"].append({
                        "op": "group",
                        "by": [columns[key_letter]],
                        "aggs": {c: ("sum" if c in numeric_targets else "first") for c in mapping["columns"].values()},
                    })
        frames.append(spec)
        mappings.append(mapping)
    if not mappings:
        raise CompileError("Without AI, the template columns could not be matched to the source columns. Add QWEN_API_KEY.")
    return {
        "summary": "The template was filled by matching column names (without AI).",
        "assumptions": [],
        "frames": frames,
        "template": mappings,
    }
