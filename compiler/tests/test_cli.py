import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from python_calamine import CalamineWorkbook

from conftest import cli_args
from excelcompiler.__main__ import main
from excelcompiler.qwen import QwenClient, QwenError, extract_json


def month_file(path, month, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = month
    ws.append([f"Sales {month}"])
    ws.append([])
    ws.append(["Outlet", "Sales", "Region"])
    for row in rows:
        ws.append(row)
    ws.append(["Total", sum(r[1] for r in rows), None])
    wb.save(path)


def fill_inputs(repo):
    month_file(repo / "input" / "jan.xlsx", "Jan", [["A", 100, "Dhaka"], ["B", 200, "Sylhet"]])
    month_file(repo / "input" / "feb.xlsx", "Feb", [["A", 10, "Dhaka"], ["C", 20, "Khulna"]])


def output_file(repo, pattern="Compiled_*.xlsx"):
    found = list((repo / "output").glob(pattern))
    assert len(found) == 1, found
    return found[0]


def report_of(repo):
    return json.loads((repo / "output" / "report.json").read_text(encoding="utf-8"))


def sheet_rows(path, name):
    return CalamineWorkbook.from_path(str(path)).get_sheet_by_name(name).to_python(skip_empty_area=False)


GOOD_PLAN = {
    "summary": "Two months together",
    "assumptions": ["Month comes from the file name"],
    "frames": [
        {"name": "all", "from": [{"source": "s2", "set": {"Month": "Jan"}}, {"source": "s1", "set": {"Month": "Feb"}}]},
        {"name": "sum", "from": ["all"], "steps": [{"op": "group", "by": ["Outlet"], "aggs": {"Sales": "sum"}}, {"op": "sort", "by": [{"column": "Sales", "desc": True}]}]},
    ],
    "sheets": [
        {"name": "Master", "frame": "all", "total_columns": ["Sales"]},
        {"name": "By Outlet", "frame": "sum"},
    ],
}


def test_offline_stack_without_key(repo, no_key):
    fill_inputs(repo)
    assert main(cli_args(repo)) == 0
    rows = sheet_rows(output_file(repo), "Compiled")
    assert rows[0][:3] == ["Outlet", "Sales", "Region"]
    assert len(rows) == 5  # header + 4 rows; the Total rows are gone
    assert sum(r[1] for r in rows[1:]) == 330
    report = report_of(repo)
    assert report["status"] == "warn" and not report["ai"]["used"]
    assert (repo / "output" / "report.md").exists() and (repo / "output" / "plan.json").exists()


def test_ai_plan_with_retry_after_bad_plan(repo, qwen):
    fill_inputs(repo)
    bad = json.loads(json.dumps(GOOD_PLAN))
    bad["frames"][1]["steps"][0]["aggs"] = {"Sale Amount": "sum"}
    qwen.replies = ["```json\n" + json.dumps(bad) + "\n```", GOOD_PLAN]
    assert main(cli_args(repo, "--instruction", "add up by month")) == 0
    assert len(qwen.requests) == 2
    assert qwen.headers[0]["Authorization"] == "Bearer sk-test"
    assert "Sale Amount" in qwen.requests[1]["messages"][-1]["content"]
    first = qwen.requests[0]
    assert first["model"] == "qwen-test" and first["response_format"] == {"type": "json_object"}
    path = output_file(repo)
    assert sheet_rows(path, "By Outlet")[1][:2] == ["B", 200]
    master = sheet_rows(path, "Master")
    assert master[-1][0] == "Total" and master[-1][1] == 330
    report = report_of(repo)
    assert report["summary"] == "Two months together" and report["ai"]["model"] == "qwen-test" and report["ai"]["used"]
    assert report["results"] == [{"name": "Master", "rows": 4}, {"name": "By Outlet", "rows": 3}]


def test_only_samples_reach_the_ai(repo, qwen, monkeypatch):
    rows = [[f"Outlet{i}", i, "R"] for i in range(50)]
    month_file(repo / "input" / "big.xlsx", "Big", rows)
    plan = {"summary": "x", "frames": [{"name": "a", "from": ["s1"]}], "sheets": [{"name": "A", "frame": "a"}]}
    qwen.replies = [plan]
    assert main(cli_args(repo)) == 0
    prompt = qwen.requests[0]["messages"][1]["content"]
    assert "Outlet2" in prompt and "Outlet3" not in prompt and "Outlet49" not in prompt

    qwen.replies = [plan]
    monkeypatch.setenv("QWEN_SAMPLE_ROWS", "0")
    assert main(cli_args(repo)) == 0
    prompt = qwen.requests[1]["messages"][1]["content"]
    assert "Outlet0" not in prompt and '"Outlet"' in prompt


def test_hidden_sheets_send_no_values_to_the_ai(repo, qwen):
    wb = Workbook()
    ws = wb.active
    ws.append(["Outlet", "Sales"])
    ws.append(["A", 1])
    ws.append(["B", 2])
    secret = wb.create_sheet("Staff")
    secret.append(["Guard", "Phone"])
    secret.append(["Private Person", "0171"])
    secret.append(["Another Person", "0172"])
    secret.sheet_state = "hidden"
    wb.save(repo / "input" / "a.xlsx")
    qwen.replies = [{"summary": "x", "frames": [{"name": "a", "from": ["s1"]}], "sheets": [{"name": "A", "frame": "a"}]}]
    assert main(cli_args(repo)) == 0
    prompt = qwen.requests[0]["messages"][1]["content"]
    assert "Private Person" not in prompt and "Guard" in prompt
    assert report_of(repo)["hidden_skipped"] == 1


def test_same_structure_tables_are_described_once(repo, qwen):
    for name in ("a", "b", "c"):
        month_file(repo / "input" / f"{name}.xlsx", "Sheet", [[f"{name}1", 1, "R"], [f"{name}2", 2, "R"]])
    qwen.replies = [{"summary": "x", "frames": [{"name": "a", "from": ["s1", "s2", "s3"]}], "sheets": [{"name": "A", "frame": "a"}]}]
    assert main(cli_args(repo)) == 0
    payload = json.loads(qwen.requests[0]["messages"][1]["content"].split("\n", 1)[1])
    assert [s.get("same_columns_as") for s in payload["sources"]] == [None, "s1", "s1"]


def test_malicious_plan_is_rejected(repo, qwen):
    fill_inputs(repo)
    evil = {"frames": [{"name": "a", "from": ["s1"], "steps": [{"op": "derive", "column": "x", "expr": "__import__('os').system('touch hacked')"}]}], "sheets": [{"name": "A", "frame": "a"}]}
    qwen.replies = [evil, evil, evil]
    assert main(cli_args(repo, "--instruction", "anything")) == 1
    assert not Path("hacked").exists()
    assert not list((repo / "output").iterdir())


def test_instruction_needs_ai(repo, no_key, capsys):
    fill_inputs(repo)
    assert main(cli_args(repo, "--instruction", "keep only Dhaka")) == 1
    assert "QWEN_API_KEY" in capsys.readouterr().err


def test_ai_down_without_instruction_falls_back_visibly(repo, qwen):
    fill_inputs(repo)
    qwen.replies = [(500, "x")] * 4
    assert main(cli_args(repo)) == 0
    report = report_of(repo)
    assert not report["ai"]["used"] and report["status"] == "warn"
    assert "HTTP 500" in report["warnings"][0]["detail"]


def test_unreadable_file_is_a_failed_check(repo, no_key):
    fill_inputs(repo)
    (repo / "input" / "broken.xlsx").write_bytes(b"PK\x03\x04not really a zip")
    assert main(cli_args(repo)) == 2
    assert output_file(repo, "*_CHECK_FAILED.xlsx")
    report = report_of(repo)
    assert report["status"] == "fail" and "broken.xlsx" in report["failures"][0]["detail"]


def test_no_input_is_an_error(repo, no_key, capsys):
    assert main(cli_args(repo)) == 1
    assert "No Excel" in capsys.readouterr().err


def test_template_mode_offline(repo, no_key):
    fill_inputs(repo)
    wb = Workbook()
    ws = wb.active
    ws.title = "Out"
    ws.append(["Outlet", "SALES", "Double"])
    ws.append([None, None, "=B2*2"])
    wb.save(repo / "template" / "Form.xlsx")
    assert main(cli_args(repo)) == 0
    saved = load_workbook(output_file(repo, "Form_*.xlsx"))["Out"]
    assert saved.max_row == 5
    assert sum(saved[f"B{r}"].value for r in range(2, 6)) == 330
    assert saved["C5"].value == "=B5*2"


def test_template_mode_with_ai_validates_formula_columns(repo, qwen):
    fill_inputs(repo)
    wb = Workbook()
    ws = wb.active
    ws.title = "Out"
    ws.append(["Outlet", "Sales", "Double"])
    ws.append([None, None, "=B2*2"])
    wb.save(repo / "template" / "Form.xlsx")
    frames = [{"name": "a", "from": ["s1", "s2"]}]
    qwen.replies = [
        {"frames": frames, "template": [{"sheet": "Out", "frame": "a", "mode": "append", "columns": {"A": "Outlet", "C": "Sales"}}]},
        {"frames": frames, "template": [{"sheet": "Out", "frame": "a", "mode": "append", "columns": {"A": "Outlet", "B": "Sales"}}]},
    ]
    assert main(cli_args(repo)) == 0
    assert "has a formula" in qwen.requests[1]["messages"][-1]["content"]


def test_two_templates_rejected(repo, no_key, capsys):
    fill_inputs(repo)
    for name in ("a.xlsx", "b.xlsx"):
        Workbook().save(repo / "template" / name)
    assert main(cli_args(repo)) == 1
    assert "one template" in capsys.readouterr().err


def test_client_adapts_to_model_quirks(qwen):
    client = QwenClient.from_env()
    qwen.replies = [
        (400, '{"message":"parameter.enable_thinking must be set to false for non-streaming calls"}'),
        (400, '{"message":"response_format is not supported by this model"}'),
        (429, "slow down"),
        {"ok": 1},
    ]
    assert extract_json(client.chat([{"role": "user", "content": "json"}])) == {"ok": 1}
    assert qwen.requests[-1]["enable_thinking"] is False
    assert "response_format" not in qwen.requests[-1]
    assert client.prompt_tokens == 100


def test_client_bad_key_message_never_shows_key(qwen):
    client = QwenClient.from_env()
    qwen.replies = [(401, "invalid key")]
    with pytest.raises(QwenError) as error:
        client.chat([{"role": "user", "content": "x"}])
    assert "sk-test" not in str(error.value) and "region" in str(error.value)
    assert len(qwen.requests) == 1


def test_extract_json_handles_prose():
    assert extract_json('Sure!\n{"a": 1}\nDone') == {"a": 1}
    with pytest.raises(QwenError):
        extract_json("no json here")
