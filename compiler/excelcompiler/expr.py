"""Safe expressions for derived columns. Parsed and whitelisted, never eval()-ed."""

from __future__ import annotations

import ast
import operator

import numpy as np
import pandas as pd

from .errors import PlanError
from .normalize import as_text, key_norm, norm_label, numeric


def resolve_column(frame: pd.DataFrame, name: str) -> str:
    if name in frame.columns:
        return name
    target = norm_label(name)
    hits = [c for c in frame.columns if norm_label(c) == target]
    if len(hits) == 1:
        return hits[0]
    raise PlanError(f"Column {name!r} not found. Available columns: {list(frame.columns)[:80]}")


def _num(value):
    return numeric(value) if isinstance(value, pd.Series) else value


def _safe_div(a, b):
    a, b = _num(a), _num(b)
    if isinstance(b, pd.Series):
        b = b.where(b != 0)
        return a / b
    if b in (0, None):
        return pd.Series(np.nan, index=a.index) if isinstance(a, pd.Series) else np.nan
    return a / b


def _round(value, digits=0):
    return _num(value).round(int(digits)) if isinstance(value, pd.Series) else round(value, int(digits))


def _abs(value):
    return _num(value).abs() if isinstance(value, pd.Series) else abs(value)


def _coalesce(*values):
    result = values[0]
    for value in values[1:]:
        if isinstance(result, pd.Series):
            result = result.where(result.notna(), value)
        elif result is None:
            result = value
    return result


def _where(condition, when_true, when_false):
    index = next((v.index for v in (condition, when_true, when_false) if isinstance(v, pd.Series)), None)
    if index is None:
        return when_true if condition else when_false
    base = when_true if isinstance(when_true, pd.Series) else pd.Series([when_true] * len(index), index=index, dtype=object)
    return base.where(condition, when_false)


def _text(value):
    return value.map(as_text).astype(object) if isinstance(value, pd.Series) else as_text(value)


def _concat(*values):
    index = next((v.index for v in values if isinstance(v, pd.Series)), None)
    if index is None:
        return "".join("" if v is None else str(v) for v in values)
    result = pd.Series([""] * len(index), index=index, dtype=object)
    for value in values:
        result = result + (_text(value).fillna("") if isinstance(value, pd.Series) else ("" if value is None else str(value)))
    return result


def _date_part(part):
    def apply(value):
        if not isinstance(value, pd.Series):
            raise PlanError(f"{part}() needs a column")
        dates = pd.to_datetime(value, errors="coerce")
        if part == "month_name":
            return dates.dt.strftime("%b-%y").astype(object)
        return getattr(dates.dt, part)

    return apply


def _string_fn(fn):
    def apply(value, *args):
        args = [int(a) for a in args]
        if isinstance(value, pd.Series):
            return _text(value).map(lambda t: None if t is None else fn(t, *args)).astype(object)
        return fn(str(value), *args)

    return apply


FUNCTIONS = {
    "safe_div": _safe_div,
    "round": _round,
    "abs": _abs,
    "coalesce": _coalesce,
    "where": _where,
    "text": _text,
    "concat": _concat,
    "year": _date_part("year"),
    "month": _date_part("month"),
    "month_name": _date_part("month_name"),
    "upper": _string_fn(lambda t: t.upper()),
    "lower": _string_fn(lambda t: t.lower()),
    "trim": _string_fn(lambda t: t.strip()),
    "left": _string_fn(lambda t, n: t[:n]),
    "right": _string_fn(lambda t, n: t[-n:] if n else ""),
}
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_COMPARE = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def _compare(op, left, right):
    if isinstance(left, str) or isinstance(right, str):
        if isinstance(left, pd.Series):
            left = left.map(key_norm)
        else:
            left = key_norm(left)
        if isinstance(right, pd.Series):
            right = right.map(key_norm)
        else:
            right = key_norm(right)
    else:
        left, right = _num(left), _num(right)
    return _COMPARE[type(op)](left, right)


def _eval(node, frame: pd.DataFrame):
    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, (int, float, str, bool)):
            return node.value
    elif isinstance(node, ast.UnaryOp):
        value = _eval(node.operand, frame)
        if isinstance(node.op, ast.USub):
            return -_num(value)
        if isinstance(node.op, ast.UAdd):
            return _num(value)
        if isinstance(node.op, ast.Not):
            return ~value if isinstance(value, pd.Series) else not value
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _num(_eval(node.left, frame)), _num(_eval(node.right, frame))
        if isinstance(left, str) or isinstance(right, str):
            raise PlanError("Arithmetic on text is not allowed; use concat() for text")
        if isinstance(node.op, ast.Div) and not isinstance(right, pd.Series) and right == 0:
            raise PlanError("Division by the constant 0")
        return _BINARY[type(node.op)](left, right)
    elif isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
        return _compare(node.ops[0], _eval(node.left, frame), _eval(node.comparators[0], frame))
    elif isinstance(node, ast.BoolOp):
        values = [_eval(v, frame) for v in node.values]
        result = values[0]
        for value in values[1:]:
            result = (result & value) if isinstance(node.op, ast.And) else (result | value)
        return result
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        name = node.func.id
        if name == "col":
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                raise PlanError('col() takes one quoted column name, e.g. col("Net Sales")')
            return frame[resolve_column(frame, node.args[0].value)]
        if name in FUNCTIONS:
            try:
                return FUNCTIONS[name](*[_eval(a, frame) for a in node.args])
            except TypeError as exc:
                raise PlanError(f"Wrong arguments for {name}(): {exc}") from None
        raise PlanError(f"Function {name}() is not allowed. Allowed: col, {', '.join(FUNCTIONS)}")
    raise PlanError(f"Expression part not allowed: {ast.dump(node)[:120]}")


def evaluate(expression: str, frame: pd.DataFrame):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 1000:
        raise PlanError("expr must be a text expression under 1000 characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise PlanError(f"Bad expression {expression!r}: {exc.msg}") from None
    return _eval(tree.body, frame)
