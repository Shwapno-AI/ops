import datetime as dt
import shutil
import subprocess
from pathlib import Path

import pytest
from openpyxl import Workbook

from excelcompiler.errors import CompileError
from excelcompiler.normalize import key_norm, parse_number
from excelcompiler.reader import build_table, read_file


def messy_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Monthly Sales Report"])
    ws.append(["Month: Jan-26"])
    ws.append([])
    ws.append(["Outlet Code", "Outlet Name", "Net Sales", "GP", "Date"])
    ws.append(["00123", "Banani", "1,234.50", 100, dt.datetime(2026, 1, 1)])
    ws.append(["00456", "Gulshan", "(200)", 50, dt.datetime(2026, 1, 2)])
    ws.append(["Outlet Code", "Outlet Name", "Net Sales", "GP", "Date"])
    ws.append(["00789", "Total Foods", "300-", 25, dt.datetime(2026, 1, 3)])
    ws.append(["00999", "Mirpur", "-", 10, dt.datetime(2026, 1, 4)])
    ws.append(["Dhaka Total", None, 1334.5, 185, None])
    ws.append(["Grand Total", None, 1334.5, 185, None])
    ws.append(["Printed by SAP"])
    hidden = wb.create_sheet("Old")
    hidden.append(["A", "B"])
    hidden.append([1, 2])
    hidden.sheet_state = "hidden"
    wb.save(path)


def test_numbers():
    assert parse_number("1,234.50") == 1234.5
    assert parse_number("(1,000)") == -1000
    assert parse_number("1,234.00-") == -1234
    assert parse_number("12%") == pytest.approx(0.12)
    assert parse_number("৳ ১২৩") == 123
    assert parse_number("2026-01-05") is None
    assert parse_number("D051") is None


def test_keys_line_up():
    assert key_norm(" d051 ") == key_norm("D051")
    assert key_norm(1001) == key_norm(1001.0) == key_norm("1001") == key_norm("1001.0")
    assert key_norm("00123") != key_norm(123)


def test_messy_sheet(tmp_path):
    path = tmp_path / "m.xlsx"
    messy_workbook(path)
    sheets = read_file(path)
    assert [s.hidden for s in sheets] == [False, True]
    table = build_table(sheets[0], "s1")
    assert table.header_row == 4
    frame = table.df
    assert len(frame) == 4
    assert table.repeated_headers == 1
    assert sorted(table.dropped_labels) == ["Dhaka Total", "Grand Total"]
    assert table.footer_rows == 1
    assert frame["Outlet Code"].tolist() == ["00123", "00456", "00789", "00999"]
    assert frame["Outlet Name"].tolist()[2] == "Total Foods"  # a business name is not a total row
    assert frame["Net Sales"].iloc[:3].tolist() == [1234.5, -200, -300]
    assert frame["Net Sales"].isna().iloc[3]
    assert frame["Date"].iloc[0] == dt.datetime(2026, 1, 1)
    assert table.above_header == [["Monthly Sales Report"], ["Month: Jan-26"]]


def test_two_level_header(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Outlet", "Jan-26", None, "Feb-26", None])
    ws.append([None, "Sales", "GP", "Sales", "GP"])
    ws.append(["A", 1, 2, 3, 4])
    ws.append(["B", 5, 6, 7, 8])
    path = tmp_path / "h.xlsx"
    wb.save(path)
    table = build_table(read_file(path)[0], "s1")
    assert table.header_depth == 2
    assert list(table.df.columns) == ["Outlet", "Jan-26 | Sales", "Jan-26 | GP", "Feb-26 | Sales", "Feb-26 | GP"]
    assert table.df["Feb-26 | GP"].sum() == 12


def test_fake_xls_utf16_tab(tmp_path):
    path = tmp_path / "sap.xls"
    text = "Report\n\nPlant\tMaterial\tQty\n------\t------\t---\nD001\t000123\t1,000.50\nD002\t000124\t25.00-\n"
    path.write_bytes(text.encode("utf-16"))
    table = build_table(read_file(path)[0], "s1")
    assert list(table.df.columns) == ["Plant", "Material", "Qty"]
    assert table.df["Material"].tolist() == ["000123", "000124"]
    assert table.df["Qty"].tolist() == [1000.5, -25]


def test_fake_xls_html(tmp_path):
    path = tmp_path / "web.xls"
    path.write_text("<html><table><tr><th colspan=3>Report</th></tr><tr><th>Code</th><th>Outlet</th><th>Sales</th></tr><tr><td>00123</td><td>A</td><td>1,000</td></tr><tr><td>00456</td><td>B</td><td>20</td></tr></table></html>")
    table = build_table(read_file(path)[0], "s1")
    assert table.header_row == 2
    assert table.df["Sales"].sum() == 1020
    assert table.df["Code"].tolist() == ["00123", "00456"]


def test_csv_semicolon(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("Outlet;Sales\nA;10\nB;20\n", encoding="utf-8")
    assert build_table(read_file(path)[0], "s1").df["Sales"].sum() == 30


@pytest.mark.skipif(not shutil.which("soffice"), reason="needs LibreOffice")
def test_real_xls(tmp_path):
    wb = Workbook()
    wb.active.append(["Outlet", "Sales"])
    wb.active.append(["A", 10])
    source = tmp_path / "old.xlsx"
    wb.save(source)
    subprocess.run(["soffice", "--headless", "--convert-to", "xls:MS Excel 97", "--outdir", str(tmp_path), str(source)], check=True, capture_output=True, timeout=120)
    table = build_table(read_file(tmp_path / "old.xls")[0], "s1")
    assert table.df["Sales"].sum() == 10


def test_password_protected_message(tmp_path):
    path = tmp_path / "locked.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 2000)
    with pytest.raises(CompileError, match="password"):
        read_file(path)
