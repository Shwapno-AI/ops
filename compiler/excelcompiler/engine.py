"""Runs a validated plan with pandas. Every step that could lose or duplicate data is checked."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .errors import PlanError
from .expr import evaluate, resolve_column
from .normalize import as_text, coerce_column, is_missing, key_norm, norm_label, numeric
from .reader import SERIAL_NAME, Table

AGGREGATIONS = {"sum", "mean", "min", "max", "count", "nunique", "first", "last", "concat_unique"}
MIN_STACK_OVERLAP = 0.5
TOLERANCE = 1e-6


@dataclass
class Check:
    name: str
    status: str  # pass | warn | fail
    detail: str = ""


@dataclass
class RunResult:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    lineage: list[dict] = field(default_factory=list)
    used_sources: set[str] = field(default_factory=set)

    def check(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name, status, detail))


def _sums_close(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE, abs(a) * 1e-9)


def _column_sum(series: pd.Series) -> float:
    return float(numeric(series).sum())


def _number_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]


def _concat_unique(series: pd.Series):
    """Join the different non-blank notes of a group, keeping their order."""
    values = dict.fromkeys(as_text(v) for v in series if not is_missing(v))
    return "; ".join(values) if values else None


def _renamed(frame: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    out = frame.rename(columns=mapping)
    repeated = [c for c in out.columns if list(out.columns).count(c) > 1]
    if repeated:
        raise PlanError(f"Renaming would create duplicate columns: {sorted(set(map(str, repeated)))}")
    return out


class Runner:
    def __init__(self, tables: dict[str, Table], instruction_given: bool = False, template_mode: bool = False):
        self.tables = tables
        self.instruction_given = instruction_given
        self.template_mode = template_mode
        self.result = RunResult()

    def _note_removed(self, frame: pd.DataFrame, columns: list[str]) -> None:
        """Dropping notes nobody asked to drop loses the very thing being compiled."""
        filled = [c for c in columns if frame[c].notna().any()]
        text = [c for c in filled if not pd.api.types.is_numeric_dtype(frame[c]) and not pd.api.types.is_datetime64_any_dtype(frame[c])]
        if text and not self.instruction_given and not self.template_mode:
            raise PlanError(f"Do not remove columns holding text unless the user asked: {text}. Keep them; rename them if they mean the same thing as another column.")
        shown = [c for c in filled if not SERIAL_NAME.match(str(c))]
        if shown and not self.template_mode:
            self.result.check("Columns left out", "warn", f"These columns hold data and are not in the result: {shown}")

    def lookup(self, name: str) -> pd.DataFrame:
        if name in self.result.frames:
            return self.result.frames[name]
        if name in self.tables:
            self.result.used_sources.add(name)
            return self.tables[name].df
        raise PlanError(f"Unknown source or frame {name!r}")

    # ---------------- stacking ----------------
    def stack(self, spec: dict) -> pd.DataFrame:
        pieces: list[pd.DataFrame] = []
        names: list[set[str]] = []
        for item in spec["from"]:
            entry = {"source": item} if isinstance(item, str) else item
            name = entry["source"]
            piece = self.lookup(name).copy()
            if entry.get("rename"):
                mapping = {resolve_column(piece, old): new for old, new in entry["rename"].items()}
                piece = _renamed(piece, mapping)
            names.append({norm_label(c) for c in piece.columns})
            for column, value in (entry.get("set") or {}).items():
                piece[column] = value
            if spec.get("add_source_columns") and name in self.tables:
                piece["Source File"] = self.tables[name].file
                piece["Source Sheet"] = self.tables[name].sheet
            pieces.append(piece)

        if len(pieces) == 1:
            return pieces[0]
        for index, columns in enumerate(names[1:], 1):
            shared = len(columns & names[0]) / max(min(len(columns), len(names[0])), 1)
            if shared < MIN_STACK_OVERLAP:
                first, other = spec["from"][0], spec["from"][index]
                raise PlanError(
                    f"Frame {spec['name']!r}: 'from' stacks rows, but {other} and {first} have too few columns in common. "
                    "Stack only tables with the same columns (use 'rename' to align names). Add columns from another table with a join step."
                )

        canonical: dict[str, str] = {}
        aligned = []
        expected: dict[str, float] = {}
        number_columns: set[str] = set()
        for piece in pieces:
            renames = {}
            for column in piece.columns:
                key = norm_label(column)
                renames[column] = canonical.setdefault(key, column)
            if len(set(renames.values())) != len(renames):
                raise PlanError(f"Two columns collapse into one after name matching: {list(piece.columns)}")
            piece = piece.rename(columns=renames)
            number_columns.update(_number_columns(piece))
            for column in piece.columns:
                expected[column] = expected.get(column, 0.0) + _column_sum(piece[column])
            aligned.append(piece.astype(object))
        stacked = pd.concat(aligned, ignore_index=True, sort=False)
        stacked = stacked.astype(object).where(stacked.notna(), None)
        for column in stacked.columns:
            stacked[column] = coerce_column(stacked[column])[0]

        rows_in = sum(len(p) for p in pieces)
        name = spec["name"]
        self.result.check(f"{name}: stack rows", "pass" if len(stacked) == rows_in else "fail", f"{rows_in} → {len(stacked)}")
        wrong = [c for c in number_columns if not _sums_close(expected[c], _column_sum(stacked[c]))]
        self.result.check(
            f"{name}: stack totals",
            "fail" if wrong else "pass",
            f"do not match: {wrong}" if wrong else f"{len(number_columns)} number columns match",
        )
        return stacked

    # ---------------- steps ----------------
    def op_rename(self, df, step):
        return _renamed(df, {resolve_column(df, k): v for k, v in step["map"].items()})

    def op_select(self, df, step):
        columns = [resolve_column(df, c) for c in step["columns"]]
        self._note_removed(df, [c for c in df.columns if c not in columns])
        return df[columns]

    def op_drop(self, df, step):
        columns = [resolve_column(df, c) for c in step["columns"]]
        self._note_removed(df, columns)
        return df.drop(columns=columns)

    def op_filter(self, df, step):
        column = df[resolve_column(df, step["column"])]
        test, value = step["test"], step.get("value")
        if test in ("is_blank", "not_blank"):
            blank = column.map(is_missing).astype(bool)
            mask = blank if test == "is_blank" else ~blank
        elif test in ("eq", "ne", "in", "not_in"):
            wanted = {key_norm(v) for v in (value if isinstance(value, list) else [value])}
            mask = column.map(key_norm).isin(wanted)
            if test in ("ne", "not_in"):
                mask = ~mask
        elif test in ("contains", "not_contains"):
            mask = column.map(lambda v: str(value).casefold() in key_norm(v))
            mask = mask.astype(bool)
            if test == "not_contains":
                mask = ~mask
        elif test in ("gt", "gte", "lt", "lte"):
            if pd.api.types.is_datetime64_any_dtype(column):
                left, right = column, pd.to_datetime(value)
            else:
                left, right = numeric(column), float(value)
            mask = {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[test]
        else:
            raise PlanError(f"Unknown filter test {test!r}")
        out = df[mask]
        if out.empty:
            raise PlanError(f"Filter {step} removed every row. Check the column and value against the profile.")
        return out

    def op_derive(self, df, step):
        value = evaluate(step["expr"], df)
        out = df.copy()
        if isinstance(value, pd.Series) and pd.api.types.is_numeric_dtype(value):
            infinite = np.isinf(value.astype("float64")).sum()
            if infinite:
                self.result.check(f"derive {step['column']}", "warn", f"{infinite} rows divided by zero; those cells were left blank")
                value = value.replace([np.inf, -np.inf], np.nan)
        out[step["column"]] = value
        return out

    def op_join(self, df, step):
        right = self.lookup(step["with"]).copy()
        pairs = [(p, p) if isinstance(p, str) else (p["left"], p["right"]) for p in step["on"]]
        left_keys = [resolve_column(df, a) for a, _ in pairs]
        right_keys = [resolve_column(right, b) for _, b in pairs]
        wanted = step.get("columns") or [c for c in right.columns if c not in right_keys]
        wanted = [resolve_column(right, c) for c in wanted]

        left = df.copy()
        left["__key"] = left[left_keys].astype(object).apply(lambda r: "\x1f".join(key_norm(v) for v in r), axis=1) if len(left) else ""
        right["__key"] = right[right_keys].astype(object).apply(lambda r: "\x1f".join(key_norm(v) for v in r), axis=1) if len(right) else ""
        right = right[right["__key"].str.strip("\x1f") != ""]

        duplicates = right["__key"].duplicated(keep=False)
        if duplicates.any():
            policy = step.get("on_duplicate", "error")
            example = right.loc[duplicates, right_keys].head(3).astype(str).values.tolist()
            if policy == "error":
                raise PlanError(
                    f"Join with {step['with']!r}: key is not unique on the right ({int(duplicates.sum())} rows, e.g. {example}). "
                    "Set on_duplicate to 'sum' or 'first', or group the right side first."
                )
            if policy == "first":
                right = right.drop_duplicates("__key", keep="first")
            elif policy == "sum":
                aggregations = {c: ("sum" if pd.api.types.is_numeric_dtype(right[c]) else "first") for c in wanted}
                right = right.groupby("__key", as_index=False, sort=False).agg(aggregations)
            else:
                raise PlanError(f"Unknown on_duplicate {policy!r}")
            self.result.check(f"join {step['with']}", "warn", f"The key repeats in that table, so the '{policy}' rule was applied")

        renames = {}
        prefix = step.get("prefix", "")
        taken = set(left.columns)
        for column in wanted:
            target = f"{prefix}{column}"
            renames[column] = f"{target} (joined)" if target in taken else target
        merged = left.merge(right[["__key", *wanted]].rename(columns=renames), on="__key", how="left", validate="m:1")

        has_key = left["__key"].str.strip("\x1f") != ""
        matched = left["__key"].isin(set(right["__key"])) & has_key
        if not matched.any():
            raise PlanError(f"Join with {step['with']!r} matched no rows. Left keys look like {left[left_keys].head(3).astype(str).values.tolist()}, right keys like {right[right_keys].head(3).astype(str).values.tolist()}.")
        missing = int((~matched).sum())
        right_only = int((~right["__key"].isin(set(left["__key"]))).sum())
        self.result.check(f"join {step['with']}: rows", "pass" if len(merged) == len(left) else "fail", f"{len(left)} → {len(merged)}")
        if missing or right_only:
            sample = left.loc[~matched, left_keys].drop_duplicates().head(5).astype(str).values.tolist()
            self.result.check(
                f"join {step['with']}: match",
                "warn",
                f"{missing} rows found no match (for example {sample}); {right_only} rows from the joined table were not used",
            )
        return merged.drop(columns="__key")

    def op_group(self, df, step):
        by = [resolve_column(df, c) for c in step["by"]]
        working = df.copy()
        named = {}
        for column, aggregation in step["aggs"].items():
            if aggregation not in AGGREGATIONS:
                raise PlanError(f"Unknown aggregation {aggregation!r}; allowed: {sorted(AGGREGATIONS)}")
            source = resolve_column(df, column)
            if aggregation in ("sum", "mean", "min", "max") and not pd.api.types.is_datetime64_any_dtype(working[source]):
                working[source] = numeric(working[source])
            named[column] = (source, aggregation)
        grouped = working.groupby(by, dropna=False, sort=True)
        for column, (source, aggregation) in named.items():
            if aggregation in ("first", "last") and pd.api.types.is_numeric_dtype(working[source]):
                distinct = grouped[source].nunique(dropna=True)
                conflicts = distinct[distinct > 1]
                if len(conflicts):
                    examples = [str(k) for k in conflicts.index[:3]]
                    if not step.get("allow_conflicts"):
                        raise PlanError(
                            f"Group by {by}: {len(conflicts)} groups have different {source!r} values (for example {examples}), so '{aggregation}' would lose numbers. "
                            "Add another column to 'by' (such as a name), or use 'sum'. Set \"allow_conflicts\": true only if keeping one value is really right."
                        )
                    self.result.check(f"Group: {column}", "warn", f"{len(conflicts)} groups had different values; one was kept (for example {examples})")
        pieces = {}
        for column, (source, aggregation) in named.items():
            if aggregation == "sum":
                pieces[column] = grouped[source].sum(min_count=1)
            elif aggregation == "concat_unique":
                pieces[column] = grouped[source].agg(_concat_unique)
            else:
                pieces[column] = grouped[source].agg(aggregation)
        out = pd.DataFrame(pieces).reset_index()
        for column, (source, aggregation) in named.items():
            if aggregation == "sum":
                ok = _sums_close(_column_sum(working[source]), _column_sum(out[column]))
                self.result.check(f"Group total: {column}", "pass" if ok else "fail", "matches" if ok else "does not match")
        return out

    def op_pivot(self, df, step):
        index = [resolve_column(df, c) for c in step["index"]]
        pivot_column = resolve_column(df, step["columns"])
        values = resolve_column(df, step["values"])
        aggregation = step.get("agg", "sum")
        if aggregation not in AGGREGATIONS:
            raise PlanError(f"Unknown aggregation {aggregation!r}")
        working = df.copy()
        if aggregation in ("sum", "mean", "min", "max"):
            working[values] = numeric(working[values])
        for column in index:
            working[column] = working[column].astype(object).where(working[column].notna(), "(blank)")
        chronological = pd.api.types.is_datetime64_any_dtype(working[pivot_column])
        if chronological:
            order = list(dict.fromkeys(pd.Timestamp(d).strftime("%b-%y") for d in sorted(working[pivot_column].dropna().unique())))
            working[pivot_column] = working[pivot_column].dt.strftime("%b-%y").astype(object)
        else:
            working[pivot_column] = working[pivot_column].map(lambda v: as_text(v) or "(blank)").astype(object)
            order = list(dict.fromkeys(working[pivot_column].tolist()))
        working[pivot_column] = working[pivot_column].astype(object).where(working[pivot_column].notna(), "(blank)")
        if "(blank)" in set(working[pivot_column]) and "(blank)" not in order:
            order.append("(blank)")
        grouped = working.groupby([*index, pivot_column], sort=False)[values]
        table = grouped.sum(min_count=1) if aggregation == "sum" else grouped.agg(aggregation)
        out = table.unstack(pivot_column).reindex(columns=order).sort_index().reset_index()
        out.columns.name = None
        if aggregation == "sum":
            ok = _sums_close(_column_sum(working[values]), float(out[order].apply(numeric).sum().sum()))
            self.result.check(f"Pivot total: {values}", "pass" if ok else "fail", "matches" if ok else "does not match")
        return out

    def op_unpivot(self, df, step):
        ids = [resolve_column(df, c) for c in step["id_columns"]]
        values = [resolve_column(df, c) for c in step["value_columns"]]
        name_col, value_col = step.get("name_column", "Attribute"), step.get("value_column", "Value")
        out = df.melt(id_vars=ids, value_vars=values, var_name=name_col, value_name=value_col)
        before = sum(_column_sum(df[c]) for c in values)
        if step.get("keep_blank") is not True:
            out = out[out[value_col].map(lambda v: not is_missing(v))]
        out[value_col] = coerce_column(out[value_col].astype(object))[0]
        ok = _sums_close(before, _column_sum(out[value_col]))
        self.result.check(f"Unpivot total: {value_col}", "pass" if ok else "fail", "matches" if ok else "does not match")
        return out.reset_index(drop=True)

    def op_sort(self, df, step):
        columns, ascending = [], []
        for item in step["by"]:
            entry = {"column": item} if isinstance(item, str) else item
            columns.append(resolve_column(df, entry["column"]))
            ascending.append(not entry.get("desc", False))
        keyed = df.copy()
        temporary = []
        for i, column in enumerate(columns):
            if keyed[column].dtype == object:
                name = f"__sort{i}"
                keyed[name] = keyed[column].map(lambda v: None if is_missing(v) else key_norm(v))
                temporary.append(name)
                columns[i] = name
        return keyed.sort_values(columns, ascending=ascending, kind="stable", na_position="last").drop(columns=temporary)

    def op_dedupe(self, df, step):
        subset = [resolve_column(df, c) for c in step.get("columns", [])] or None
        out = df.drop_duplicates(subset=subset, keep=step.get("keep", "first"))
        removed = len(df) - len(out)
        if removed:
            self.result.check("dedupe", "warn", f"{removed} duplicate rows were removed")
        return out

    def op_fill_down(self, df, step):
        out = df.copy()
        for column in step["columns"]:
            name = resolve_column(df, column)
            out[name] = out[name].ffill()
        return out

    def op_to_number(self, df, step):
        out = df.copy()
        for column in step["columns"]:
            name = resolve_column(df, column)
            out[name] = numeric(out[name])
        return out

    def op_to_text(self, df, step):
        out = df.copy()
        for column in step["columns"]:
            name = resolve_column(df, column)
            out[name] = out[name].map(as_text).astype(object)
        return out

    def op_to_date(self, df, step):
        out = df.copy()
        for column in step["columns"]:
            name = resolve_column(df, column)
            parsed = pd.to_datetime(out[name], format=step.get("format"), dayfirst=step.get("dayfirst", True), errors="coerce")
            lost = int((out[name].notna() & parsed.isna()).sum())
            if lost > 0.1 * max(int(out[name].notna().sum()), 1):
                raise PlanError(f"to_date on {name!r} failed for {lost} rows; give the right 'format'.")
            if lost:
                self.result.check(f"to_date {name}", "warn", f"{lost} cells could not be read as dates")
            out[name] = parsed
        return out

    def op_limit(self, df, step):
        return df.head(int(step["n"]))

    # ---------------- run ----------------
    def run(self, plan: dict) -> RunResult:
        for spec in plan["frames"]:
            name = spec["name"]
            frame = self.stack(spec)
            self.result.lineage.append({"frame": name, "step": "from " + ", ".join(i if isinstance(i, str) else i["source"] for i in spec["from"]), "rows_in": None, "rows_out": len(frame)})
            for step in spec.get("steps", []):
                op = step.get("op")
                handler = getattr(self, f"op_{op}", None)
                if handler is None:
                    raise PlanError(f"Unknown op {op!r}")
                before = len(frame)
                try:
                    frame = handler(frame, step)
                except PlanError:
                    raise
                except KeyError as exc:
                    raise PlanError(f"Frame {name!r}, op {op!r}: missing setting {exc}") from None
                except (ValueError, TypeError) as exc:
                    raise PlanError(f"Frame {name!r}, op {op!r} failed: {exc}") from None
                self.result.lineage.append({"frame": name, "step": op, "rows_in": before, "rows_out": len(frame)})
            self.result.frames[name] = frame.reset_index(drop=True)
        return self.result


def run_plan(plan: dict, tables: dict[str, Table], instruction_given: bool = False, template_mode: bool = False) -> RunResult:
    return Runner(tables, instruction_given, template_mode).run(plan)
