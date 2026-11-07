import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.table import Table as ExcelTable
from python_calamine import CalamineWorkbook

from excelcompiler.engine import RunResult
from excelcompiler.template import analyze_template, fill_template, recalculation_check, verify_template

needs_office = pytest.mark.skipif(not shutil.which("soffice"), reason="needs LibreOffice")


def values_after_recalc(path, folder):
    subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(folder), str(path)], check=True, capture_output=True, timeout=180)
    return CalamineWorkbook.from_path(str(Path(folder) / path.name))


def append_template(path, table_object=False):
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws["A1"] = "Outlet Report"
    ws["A2"] = "Month:"
    ws.merge_cells("A1:E1")
    ws.append([])
    ws.append(["Outlet", "Sales", "Cost", "Profit", "Note"])
    for cell in ws[4]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="FFCC00")
    ws["B5"].number_format = "#,##0.00"
    ws["D5"] = "=B5-C5"
    ws["D5"].font = Font(color="FF0000")
    ws["A6"] = "Total"
    ws["B6"] = "=SUM(B5:B5)"
    ws["D6"] = "=SUM(D5:D5)"
    ws["A6"].font = Font(bold=True)
    ws["A8"] = "Prepared by Ops"
    ws["E8"] = "=B6*2"
    ws.conditional_formatting.add("D5:D5", CellIsRule(operator="lessThan", formula=["0"], fill=PatternFill("solid", bgColor="FF0000")))
    top = wb.create_sheet("Top")
    top["A1"] = "All sales"
    top["B1"] = "=Report!B6"
    top["A2"] = "Direct range"
    top["B2"] = "=SUM(Report!C5:C5)"
    wb.save(path)


def frame_of(n):
    return pd.DataFrame({"Outlet": [f"O{i}" for i in range(n)], "Sales": [float(i + 1) * 10 for i in range(n)], "Cost": [float(i + 1) for i in range(n)]})


def run_fill(path, tmp_path, plan, frames):
    info = analyze_template(path)
    result = RunResult(frames=frames)
    out = tmp_path / "out.xlsx"
    audit = fill_template(info, plan, result, out)
    verify_template(out, audit, result)
    return out, result


def test_analysis(tmp_path):
    path = tmp_path / "t.xlsx"
    append_template(path)
    sheet = analyze_template(path).sheets["Report"]
    assert (sheet.header_row, sheet.data_start, sheet.footer_row, sheet.last_data_row) == (4, 5, 6, 5)
    assert sheet.columns["D"].formula == "=B5-C5"
    assert sheet.columns["A"].header == "Outlet"


@needs_office
def test_append_grows_past_footer_and_formulas_follow(tmp_path):
    path = tmp_path / "t.xlsx"
    append_template(path)
    plan = {"template": [{"sheet": "Report", "frame": "f", "mode": "append", "columns": {"A": "Outlet", "B": "Sales", "C": "Cost"}}], "cells": [{"sheet": "Report", "cell": "B2", "value": "Nov-26"}]}
    out, result = run_fill(path, tmp_path, plan, {"f": frame_of(50)})
    assert not [c for c in result.checks if c.status == "fail"]

    wb = load_workbook(out)
    ws = wb["Report"]
    assert ws["D54"].value == "=B54-C54"
    assert ws["A55"].value == "Total"
    assert ws["B55"].value == "=SUM(B5:B54)"
    assert ws["D55"].value == "=SUM(D5:D54)"
    assert ws["E57"].value == "=B55*2"
    assert ws["A57"].value == "Prepared by Ops"
    assert wb["Top"]["B1"].value == "=Report!B55"
    assert wb["Top"]["B2"].value == "=SUM(Report!C5:C54)"
    assert ws["B2"].value == "Nov-26"
    assert ws["A4"].font.bold and ws["A4"].fill.fgColor.rgb.endswith("FFCC00")
    assert ws["B54"].number_format == "#,##0.00"
    assert ws["D54"].font.color.rgb.endswith("FF0000")
    assert "A1:E1" in [str(m) for m in ws.merged_cells.ranges]
    assert any("D5:D54" in str(cf.sqref) for cf in ws.conditional_formatting)

    expected = sum((i + 1) * 10 for i in range(50))
    book = values_after_recalc(out, tmp_path / "calc")
    report = book.get_sheet_by_name("Report").to_python(skip_empty_area=False)
    assert report[54][1] == expected
    assert report[54][3] == expected - sum(i + 1 for i in range(50))
    assert book.get_sheet_by_name("Top").to_python(skip_empty_area=False)[0][1] == expected
    assert book.get_sheet_by_name("Top").to_python(skip_empty_area=False)[1][1] == sum(i + 1 for i in range(50))
    recalculation_check(out, result)
    assert [c for c in result.checks if c.name == "Formula check"][0].status == "pass"


def test_excel_table_and_filter_grow(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Outlet", "Sales", "Double"])
    ws.append([None, None, "=B2*2"])
    table = ExcelTable(displayName="Data1", ref="A1:C2")
    ws.add_table(table)
    path = tmp_path / "t.xlsx"
    wb.save(path)
    plan = {"template": [{"sheet": "Data", "frame": "f", "mode": "append", "columns": {"A": "Outlet", "B": "Sales"}}]}
    out, result = run_fill(path, tmp_path, plan, {"f": frame_of(10)})
    saved = load_workbook(out)["Data"]
    assert saved.tables["Data1"].ref == "A1:C11"
    assert saved["C11"].value == "=B11*2"
    assert not [c for c in result.checks if c.status == "fail"]


def test_fewer_rows_than_space_clears_old_data(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Outlet", "Sales", "Region"])
    for i in range(6):
        ws.append([f"old{i}", 999, "stale"])
    path = tmp_path / "t.xlsx"
    wb.save(path)
    info_sheet = analyze_template(path).sheets["Sheet"]
    assert info_sheet.last_data_row == 7
    plan = {"template": [{"sheet": "Sheet", "frame": "f", "mode": "append", "columns": {"A": "Outlet", "B": "Sales"}}]}
    out, result = run_fill(path, tmp_path, plan, {"f": frame_of(2)})
    saved = load_workbook(out)["Sheet"]
    rows = [[c.value for c in r] for r in saved["A2:C7"]]
    assert rows[0] == ["O0", 10, None]
    assert rows[2] == [None, None, None]
    assert not [c for c in result.checks if c.status == "fail"]


def test_fill_by_key(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "KPI"
    ws.append(["Outlet Code", "Outlet Name", "Sales", "Rate"])
    for code, name in [("D001", "Banani"), ("d002 ", "Gulshan"), ("D003", "Uttara"), ("D004", "Mirpur")]:
        ws.append([code, name, 111, f"=C{ws.max_row + 1}/100"])
    ws.append(["Total", None, "=SUM(C2:C5)", None])
    path = tmp_path / "t.xlsx"
    wb.save(path)
    sheet = analyze_template(path).sheets["KPI"]
    assert sheet.suggested_key == "A"
    frame = pd.DataFrame({"Code": ["D001", "D002", "D004", "D999"], "Sales": [10.0, 20.0, 30.0, 40.0]})
    plan = {"template": [{"sheet": "KPI", "frame": "f", "mode": "fill_by_key", "key": {"A": "Code"}, "columns": {"C": "Sales"}}]}
    out, result = run_fill(path, tmp_path, plan, {"f": frame})
    saved = load_workbook(out)["KPI"]
    assert [saved[f"C{r}"].value for r in range(2, 6)] == [10, 20, None, 30]
    assert saved["D2"].value == "=C2/100"
    assert saved["C6"].value == "=SUM(C2:C5)"
    details = " ".join(c.detail for c in result.checks if c.status == "warn")
    assert "D003" in details
    assert "d999" in details
    assert not [c for c in result.checks if c.status == "fail"]


def test_source_text_never_becomes_a_formula(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Sales"])
    path = tmp_path / "t.xlsx"
    wb.save(path)
    frame = pd.DataFrame({"Name": ['=HYPERLINK("http://x","click")'], "Sales": [1.0]})
    plan = {"template": [{"sheet": "Sheet", "frame": "f", "mode": "append", "columns": {"A": "Name", "B": "Sales"}}]}
    out, _ = run_fill(path, tmp_path, plan, {"f": frame})
    assert load_workbook(out)["Sheet"]["A2"].data_type == "s"


def test_total_directly_under_header_moves_down(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Outlet", "Sales"])
    ws.append(["Total", "=SUM(B1:B1)"])
    path = tmp_path / "t.xlsx"
    wb.save(path)
    plan = {"template": [{"sheet": "Sheet", "frame": "f", "mode": "append", "columns": {"A": "Outlet", "B": "Sales"}}]}
    out, result = run_fill(path, tmp_path, plan, {"f": frame_of(3)})
    saved = load_workbook(out)["Sheet"]
    assert [saved[f"A{r}"].value for r in range(2, 6)] == ["O0", "O1", "O2", "Total"]
    assert not [c for c in result.checks if c.status == "fail"]


def test_fill_by_key_stays_inside_the_table(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "KPI"
    ws.append(["Code", "Name", "Sales"])
    ws.append(["D1", "A", None])
    ws.append(["D2", "B", None])
    ws.append(["Zone Total", None, "=SUM(C2:C3)"])
    ws.append(["D3", "C", None])
    ws.append(["Grand Total", None, "=C4+C5"])
    ws.append([None, None, None])
    ws.append(["Prepared by", None, "Ops Team"])
    path = tmp_path / "t.xlsx"
    wb.save(path)
    frame = pd.DataFrame({"Code": ["D1", "D2", "D3"], "Sales": [1.0, 2.0, 3.0]})
    plan = {"template": [{"sheet": "KPI", "frame": "f", "mode": "fill_by_key", "key": {"A": "Code"}, "columns": {"C": "Sales"}}]}
    out, result = run_fill(path, tmp_path, plan, {"f": frame})
    saved = load_workbook(out)["KPI"]
    assert [saved[f"C{r}"].value for r in (2, 3, 5)] == [1, 2, 3]
    assert saved["C4"].value == "=SUM(C2:C3)"
    assert saved["C8"].value == "Ops Team"
    assert not [c for c in result.checks if c.status != "pass" and "key" in c.name]


def test_macro_workbook_keeps_its_macros(tmp_path):
    import xlsxwriter
    import zipfile

    payload = tmp_path / "vbaProject.bin"
    payload.write_bytes(b"fake macro bytes" * 50)
    path = tmp_path / "t.xlsm"
    book = xlsxwriter.Workbook(path)
    sheet = book.add_worksheet("Data")
    sheet.write_row(0, 0, ["Outlet", "Sales"])
    book.add_vba_project(str(payload))
    book.close()
    info = analyze_template(path)
    result = RunResult(frames={"f": frame_of(2)})
    out = tmp_path / "out.xlsm"
    plan = {"template": [{"sheet": "Data", "frame": "f", "mode": "append", "columns": {"A": "Outlet", "B": "Sales"}}]}
    fill_template(info, plan, result, out)
    with zipfile.ZipFile(out) as archive:
        assert archive.read("xl/vbaProject.bin") == payload.read_bytes()
        assert b"macroEnabled" in archive.read("[Content_Types].xml")
