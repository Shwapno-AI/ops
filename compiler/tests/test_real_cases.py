"""Regressions from the first real runs: each of these failed before it was fixed."""

import json

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from conftest import cli_args
from excelcompiler.__main__ import main
from excelcompiler.engine import run_plan
from excelcompiler.errors import PlanError
from excelcompiler.reader import Table, build_table, key_overlap, read_file


def zone_sheet(path, rows, note_header="Remarks", sub_note=None, rho=False):
    """The shape zone managers really returned: a label line under the header and a 'Total Guard:' footer."""
    wb = Workbook()
    ws = wb.active
    head = ["SL", "Outlet Code", "Outlet Name"] + (["Zone Head"] if rho else []) + ["Day Shift", "Night Shift", "Total Guard", "DMA Costing", note_header]
    ws.append(head)
    ws.append([None, None, None] + (["RHO"] if rho else []) + ["Total Day Guard", "Total Night Guard", None, None, sub_note])
    day = night = 0
    for i, (code, name, d, n, note) in enumerate(rows, 1):
        ws.append([i, code, name] + (["Mr. X"] if rho else []) + [d, n, d + n, 1000.5, note])
        day, night = day + d, night + n
    ws.append([None, None, "Total Guard:"] + ([None] if rho else []) + [day, night, day + night, 1000.5 * len(rows), None])
    wb.save(path)


LIST = [("D001", "Uttara", 3, 1, None), ("D002", "Banani", 2, 1, None), ("D003", "Mirpur", 1, 0, None), ("D004", "Gulshan", 2, 2, None)]


def read(path, table_id="s1"):
    return build_table(read_file(path)[0], table_id)


def test_total_guard_footer_and_label_line_are_not_data(tmp_path):
    path = tmp_path / "z.xlsx"
    zone_sheet(path, LIST)
    table = read(path)
    assert len(table.df) == 4
    assert table.dropped_labels == ["Total Guard:"]
    assert table.df["Day Shift"].sum() == 8  # not 16, and numeric rather than text
    assert pd.api.types.is_numeric_dtype(table.df["Night Shift"])


def test_label_line_names_columns_that_had_no_header(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["SL", "Outlet Code", "Outlet Name", None, "Day Shift", None])
    ws.append([None, None, None, "RHO", "Total Day Guard", "Status & Reason"])
    for i in range(1, 6):
        ws.append([i, f"D{i}", f"Name {i}", "Mr. X", i, "ok"])
    path = tmp_path / "z.xlsx"
    wb.save(path)
    table = read(path)
    assert list(table.df.columns) == ["SL", "Outlet Code", "Outlet Name", "RHO", "Day Shift", "Status & Reason"]
    assert len(table.df) == 5


def test_repeated_headers_with_a_label_line(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["SL", "Outlet Code", "Day Shift", "Night Shift", "Day Shift", "Night Shift"])
    ws.append([None, None, "Total Day", "Total Night", "Feedback", "Feedback"])
    for i in range(1, 6):
        ws.append([i, f"D{i}", i, 1, "note", None])
    path = tmp_path / "z.xlsx"
    wb.save(path)
    assert list(read(path).df.columns) == ["SL", "Outlet Code", "Day Shift", "Night Shift", "Day Shift | Feedback", "Night Shift | Feedback"]


def test_group_titles_above_a_line_of_counts(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append([None, None, "As-Is Status", None, "To-Be Status", None])
    ws.append([None, None, 65, 46, 24, 22])
    ws.append(["Outlet Code", "Outlet Name", "Day Shift", "Night Shift", "Day Shift", "Night Shift"])
    for i in range(1, 6):
        ws.append([f"D{i}", f"Name {i}", i, 1, 1, 0])
    path = tmp_path / "z.xlsx"
    wb.save(path)
    columns = list(read(path).df.columns)
    assert columns[2:] == ["As-Is Status | Day Shift", "As-Is Status | Night Shift", "To-Be Status | Day Shift", "To-Be Status | Night Shift"]


def test_unlabelled_sum_row_is_removed_but_a_normal_last_row_stays(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Outlet Code", "Sales", "GP"])
    for row in (["D1", 10, 1], ["D2", 20, 2], ["D3", 30, 3], [None, 60, 6]):
        ws.append(row)
    path = tmp_path / "a.xlsx"
    wb.save(path)
    table = read(path)
    assert len(table.df) == 3 and table.df["Sales"].sum() == 60

    wb = Workbook()
    ws = wb.active
    ws.append(["Outlet Code", "Sales", "GP"])
    for row in (["D1", 10, 1], ["D2", 20, 2], ["D3", 30, 3], ["D4", 60, 7]):
        ws.append(row)
    path = tmp_path / "b.xlsx"
    wb.save(path)
    assert len(read(path).df) == 4


def test_total_foods_is_still_a_name(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Outlet Code", "Outlet Name", "Sales", "GP"])
    ws.append(["D1", "Total Foods", 10, 1])
    ws.append(["D2", "Banani", 20, 2])
    ws.append(["Total Foods Ltd", None, 30, 3])
    path = tmp_path / "a.xlsx"
    wb.save(path)
    table = read(path)
    # the last row sums the others, but it has a name and only a verified sum removes it
    assert "Total Foods" in table.df["Outlet Name"].tolist()


def test_mixed_text_and_number_pieces_do_not_raise_a_false_alarm():
    """One source reads as numbers, another as text with a stray label. Totals must still match."""
    a = pd.DataFrame({"Code": ["A", "B"], "Day": [1.0, 2.0]})
    b = pd.DataFrame({"Code": ["C", "D"], "Day": pd.Series([3.0, "n/a?"], dtype=object)})
    tables = {"s1": Table("s1", "a", "S", False, 1, 1, a), "s2": Table("s2", "b", "S", False, 1, 1, b)}
    result = run_plan({"frames": [{"name": "f", "from": ["s1", "s2"]}]}, tables)
    assert not [c for c in result.checks if c.status == "fail"]


def table_of(table_id, **columns):
    return Table(table_id, f"{table_id}.xlsx", "S", False, 1, 1, pd.DataFrame(columns))


def test_stacking_unrelated_tables_is_rejected():
    tables = {
        "s1": table_of("s1", Code=["A", "B"], Zone=["N", "S"]),
        "s2": table_of("s2", **{"Outlet Code": ["A", "B"], "Net Sales": [1.0, 2.0], "GP": [1.0, 1.0]}),
    }
    with pytest.raises(PlanError, match="too few columns in common"):
        run_plan({"frames": [{"name": "f", "from": ["s1", "s2"]}]}, tables)


def test_dropping_notes_nobody_asked_to_drop_is_rejected():
    tables = {"s1": table_of("s1", Code=["A", "B"], Sales=[1.0, 2.0], Feedback=["bad", None])}
    plan = {"frames": [{"name": "f", "from": ["s1"], "steps": [{"op": "drop", "columns": ["Feedback"]}]}]}
    with pytest.raises(PlanError, match="Do not remove columns holding text"):
        run_plan(plan, tables)
    result = run_plan(plan, tables, instruction_given=True)  # the user asked for it, so it is allowed and reported
    assert any(c.name == "Columns left out" and "Feedback" in c.detail for c in result.checks)


def test_first_cannot_silently_lose_different_numbers():
    tables = {"s1": table_of("s1", Code=["DK10", "DK10", "D1"], Name=["Haval", "NFD", "A"], Day=[2.0, 1.0, 5.0])}
    step = {"op": "group", "by": ["Code"], "aggs": {"Day": "first"}}
    with pytest.raises(PlanError, match="would lose numbers"):
        run_plan({"frames": [{"name": "f", "from": ["s1"], "steps": [step]}]}, tables)
    fixed = {"op": "group", "by": ["Code", "Name"], "aggs": {"Day": "first"}}
    result = run_plan({"frames": [{"name": "f", "from": ["s1"], "steps": [fixed]}]}, tables)
    assert result.frames["f"]["Day"].sum() == 8


def test_concat_unique_keeps_every_note_once():
    tables = {"s1": table_of("s1", Code=["A", "A", "A", "B"], Note=["x", None, "y", None], Day=[1.0, 1.0, 1.0, 2.0])}
    step = {"op": "group", "by": ["Code"], "aggs": {"Day": "first", "Note": "concat_unique"}}
    frame = run_plan({"frames": [{"name": "f", "from": ["s1"], "steps": [step]}]}, tables).frames["f"]
    assert frame["Note"].tolist()[0] == "x; y" and pd.isna(frame["Note"].tolist()[1])


def test_overlap_tells_the_planner_about_shared_lists(tmp_path):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    zone_sheet(a, LIST)
    zone_sheet(b, LIST[:2])
    found = key_overlap([read(a, "s1"), read(b, "s2")])
    assert found[0]["column"] == "Outlet Code" and found[0]["keys_in_2_or_more_tables"] == 2
    assert found[0]["same_numbers_pct"] == 100


def stack_plan():
    return {"summary": "Stack", "frames": [{"name": "all", "from": ["s1", "s2"]}], "sheets": [{"name": "All", "frame": "all"}]}


def merged_plan():
    return {
        "summary": "One row per outlet",
        "frames": [{
            "name": "all",
            "from": ["s1", {"source": "s2", "rename": {"Reason": "Remarks"}}],
            "steps": [{"op": "group", "by": ["Outlet Code", "Outlet Name"], "aggs": {"Day Shift": "first", "Night Shift": "first", "Total Guard": "first", "DMA Costing": "first", "Remarks": "concat_unique"}}],
        }],
        "sheets": [{"name": "All", "frame": "all", "total_columns": ["Total Guard"]}],
    }


def test_zone_files_merge_to_one_row_per_outlet_with_every_note(repo, qwen):
    """The real job: everyone returned the same list. Blind stacking double counts, so it is sent back."""
    zone_sheet(repo / "input" / "a.xlsx", [(c, n, d, x, "needs guard" if c == "D001" else None) for c, n, d, x, _ in LIST])
    zone_sheet(repo / "input" / "b.xlsx", [(c, n, d, x, "wrong data" if c == "D003" else None) for c, n, d, x, _ in LIST], note_header="Reason")
    qwen.replies = [stack_plan(), merged_plan()]
    assert main(cli_args(repo)) == 0
    assert "double counts" in qwen.requests[1]["messages"][-1]["content"]
    payload = json.loads(qwen.requests[0]["messages"][1]["content"].split("\n", 1)[1])
    assert payload["key_overlap"][0]["same_numbers_pct"] == 100

    path = next((repo / "output").glob("Compiled_*.xlsx"))
    sheet = load_workbook(path)["All"]
    rows = {r[0]: r for r in sheet.iter_rows(min_row=2, values_only=True) if r[0]}
    assert set(rows) == {"D001", "D002", "D003", "D004", "Total"}
    assert rows["D001"][6] == "needs guard" and rows["D003"][6] == "wrong data"
    assert sum(rows[c][4] for c in ("D001", "D002", "D003", "D004")) == 12


def test_stacking_shared_lists_without_ai_warns_about_double_counting(repo, no_key):
    zone_sheet(repo / "input" / "a.xlsx", LIST)
    zone_sheet(repo / "input" / "b.xlsx", LIST)
    assert main(cli_args(repo)) == 0
    report = json.loads((repo / "output" / "report.json").read_text(encoding="utf-8"))
    assert any(w["name"] == "Repeated records" for w in report["warnings"])


def sample_inputs(repo):
    sales = Workbook()
    ws = sales.active
    ws.append(["Outlet Code", "Outlet Name", "Net Sales"])
    ws.append(["D001", "A", 100])
    ws.append(["D002", "B", 200])
    sales.save(repo / "input" / "sales.xlsx")
    zones = Workbook()
    ws = zones.active
    ws.append(["Code", "Zone"])
    ws.append(["D001", "North"])
    ws.append(["D002", "South"])
    zones.save(repo / "input" / "zones.xlsx")
    template = Workbook()
    ws = template.active
    ws.title = "Report"
    ws.append(["Outlet Code", "Outlet Name", "Zone", "Net Sales"])
    ws.append([None, None, None, None])
    template.save(repo / "template" / "Form.xlsx")


def test_the_empty_template_mistake_cannot_pass_as_success(repo, qwen):
    """Real Qwen stacked unrelated tables and chose fill_by_key on an empty template; the file came out blank."""
    sample_inputs(repo)
    wrong_stack = {"frames": [{"name": "f", "from": ["s1", "s2"], "steps": [{"op": "join", "with": "s2", "on": [{"left": "Outlet Code", "right": "Code"}]}]}], "template": [{"sheet": "Report", "frame": "f", "mode": "append", "columns": {"A": "Outlet Code"}}]}
    good_frame = {"name": "f", "from": ["s1"], "steps": [{"op": "join", "with": "s2", "on": [{"left": "Outlet Code", "right": "Code"}], "columns": ["Zone"]}]}
    wrong_mode = {"frames": [good_frame], "template": [{"sheet": "Report", "frame": "f", "mode": "fill_by_key", "key": {"A": "Outlet Code"}, "columns": {"B": "Outlet Name", "C": "Zone", "D": "Net Sales"}}]}
    good = {"frames": [good_frame], "template": [{"sheet": "Report", "frame": "f", "mode": "append", "columns": {"A": "Outlet Code", "B": "Outlet Name", "C": "Zone", "D": "Net Sales"}}]}
    qwen.replies = [wrong_stack, wrong_mode, good]
    assert main(cli_args(repo, "--instruction", "fill the template")) == 0
    assert "in both 'from' and a join" in qwen.requests[1]["messages"][-1]["content"]
    assert "Use mode 'append'" in qwen.requests[2]["messages"][-1]["content"]
    payload = json.loads(qwen.requests[0]["messages"][1]["content"].split("\n", 1)[1])
    assert payload["template"][0]["suggested_mode"] == "append"

    sheet = load_workbook(next((repo / "output").glob("Form_*.xlsx")))["Report"]
    assert [c.value for c in sheet[3]] == ["D002", "B", "South", 200]


def test_a_mapped_column_with_no_data_is_sent_back(repo, qwen):
    sample_inputs(repo)
    frame = {"name": "f", "from": ["s1"], "steps": [{"op": "derive", "column": "Zone", "expr": "None"}]}
    good_frame = {"name": "f", "from": ["s1"]}
    qwen.replies = [
        {"frames": [frame], "template": [{"sheet": "Report", "frame": "f", "mode": "append", "columns": {"A": "Outlet Code", "C": "Zone"}}]},
        {"frames": [good_frame], "template": [{"sheet": "Report", "frame": "f", "mode": "append", "columns": {"A": "Outlet Code", "D": "Net Sales"}}]},
    ]
    assert main(cli_args(repo)) == 0
    assert "completely empty" in qwen.requests[1]["messages"][-1]["content"]
