import pandas as pd
import pytest

from excelcompiler.engine import run_plan
from excelcompiler.errors import PlanError
from excelcompiler.expr import evaluate
from excelcompiler.plan import validate_plan
from excelcompiler.reader import Table


def table(table_id, frame, file="f.xlsx", sheet="Sheet1"):
    return Table(table_id, file, sheet, False, 1, 1, frame)


@pytest.fixture
def tables():
    a = pd.DataFrame({"Outlet": ["A", "B", "C"], "Sales": [100.0, 200.0, None], "Month": ["Jan", "Jan", "Jan"]})
    b = pd.DataFrame({"outlet": ["A", "D"], "SALES": [10.0, 20.0], "Month": ["Feb", "Feb"], "Extra": ["x", "y"]})
    lookup = pd.DataFrame({"Code": ["a ", "B"], "Region": ["Dhaka", "Sylhet"]})
    dup = pd.DataFrame({"Code": ["A", "A"], "Region": ["Dhaka", "Sylhet"], "Target": [1.0, 2.0]})
    return {"s1": table("s1", a), "s2": table("s2", b, "g.xlsx"), "s3": table("s3", lookup), "s4": table("s4", dup)}


def run(tables, *steps, origins=("s1", "s2"), **extra):
    return run_plan({"frames": [{"name": "f", "from": list(origins), "steps": list(steps), **extra}]}, tables)


def statuses(result):
    return {c.status for c in result.checks}


def test_stack_aligns_names_and_keeps_totals(tables):
    result = run(tables, add_source_columns=True)
    frame = result.frames["f"]
    assert len(frame) == 5
    assert list(frame.columns)[:3] == ["Outlet", "Sales", "Month"]
    assert frame["Sales"].sum() == 330
    assert frame["Source File"].tolist()[-1] == "g.xlsx"
    assert "fail" not in statuses(result)


def test_group_and_pivot_totals(tables):
    result = run(tables, {"op": "group", "by": ["Outlet"], "aggs": {"Sales": "sum"}})
    assert result.frames["f"].set_index("Outlet")["Sales"]["A"] == 110
    assert pd.isna(result.frames["f"].set_index("Outlet")["Sales"]["C"])  # blank stays blank, not 0
    result = run(tables, {"op": "pivot", "index": ["Outlet"], "columns": "Month", "values": "Sales"})
    assert list(result.frames["f"].columns) == ["Outlet", "Jan", "Feb"]
    assert "fail" not in statuses(result)


def test_unpivot_total(tables):
    frame = pd.DataFrame({"Outlet": ["A", "B"], "Jan": [1.0, 2.0], "Feb": [3.0, None]})
    result = run({"s1": table("s1", frame)}, {"op": "unpivot", "id_columns": ["Outlet"], "value_columns": ["Jan", "Feb"], "name_column": "Month", "value_column": "Sales"}, origins=["s1"])
    assert result.frames["f"]["Sales"].sum() == 6
    assert len(result.frames["f"]) == 3


def test_join_normalises_keys_and_reports_misses(tables):
    result = run(tables, {"op": "join", "with": "s3", "on": [{"left": "Outlet", "right": "Code"}], "columns": ["Region"]}, origins=["s1"])
    frame = result.frames["f"]
    assert frame["Region"].tolist()[:2] == ["Dhaka", "Sylhet"]
    assert len(frame) == 3
    assert any(c.status == "warn" and "found no match" in c.detail for c in result.checks)


def test_join_never_multiplies_rows(tables):
    step = {"op": "join", "with": "s4", "on": [{"left": "Outlet", "right": "Code"}]}
    with pytest.raises(PlanError, match="not unique"):
        run(tables, step, origins=["s1"])
    result = run(tables, {**step, "on_duplicate": "sum", "columns": ["Target"]}, origins=["s1"])
    assert len(result.frames["f"]) == 3
    assert result.frames["f"]["Target"].iloc[0] == 3


def test_filter_and_empty_result(tables):
    result = run(tables, {"op": "filter", "column": "Month", "test": "eq", "value": " jan "}, origins=["s1"])
    assert len(result.frames["f"]) == 3
    with pytest.raises(PlanError, match="removed every row"):
        run(tables, {"op": "filter", "column": "Month", "test": "eq", "value": "Dec"}, origins=["s1"])


def test_derive(tables):
    result = run(tables, {"op": "derive", "column": "Half", "expr": 'safe_div(col("Sales"), 2)'}, origins=["s1"])
    assert result.frames["f"]["Half"].iloc[0] == 50
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [0.0, 1.0]})
    assert evaluate('safe_div(col("a"), col("b"))', frame).isna().iloc[0]
    assert evaluate('where(col("a") > 1, "big", "small")', frame).tolist() == ["small", "big"]
    assert evaluate('concat(col("a"), "-x")', frame).tolist() == ["1-x", "2-x"]
    assert evaluate('coalesce(col("a"), 0) + 1', frame).tolist() == [2, 3]


@pytest.mark.parametrize("expr", [
    "__import__('os').system('id')",
    "open('/etc/passwd')",
    "col('a').__class__",
    "(lambda: 1)()",
    "[x for x in (1,2)]",
    "exec('1')",
    "f'{1}'",
    "col('a')[0]",
])
def test_expressions_cannot_escape(expr):
    with pytest.raises(PlanError):
        evaluate(expr, pd.DataFrame({"a": [1]}))


def test_validation_messages():
    errors = validate_plan({"frames": [{"name": "x", "from": ["nope"], "steps": [{"op": "shell"}]}], "sheets": []}, {"s1"}, None)
    text = " ".join(errors)
    assert "unknown source" in text and "unknown op" in text and "'sheets'" in text
