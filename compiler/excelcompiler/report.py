"""Builds the run report as data for the website, plus a readable report.md."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .engine import RunResult
from .reader import Table

STATUS_TEXT = {
    "ok": "Done. All checks matched.",
    "warn": "Done. Please look at the items below.",
    "fail": "A check failed. Do not use this file before reviewing it.",
}


@dataclass
class RunInfo:
    stamp: str
    files: list[str]
    ignored: list[str] = field(default_factory=list)
    instruction: str = ""
    template: str | None = None
    output: str = ""
    plan: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    read_failures: list[str] = field(default_factory=list)
    empty_sheets: list[str] = field(default_factory=list)
    ai_used: bool = False
    ai_model: str | None = None
    ai_attempts: int = 0
    ai_problem: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    sample_rows: int = 0


def _table_row(table: Table) -> dict:
    removed = []
    if table.dropped_labels:
        shown = ", ".join(sorted(set(table.dropped_labels))[:3])
        removed.append(f"{len(table.dropped_labels)} total rows ({shown})")
    if table.repeated_headers:
        removed.append(f"{table.repeated_headers} repeated headers")
    if table.footer_rows:
        removed.append(f"{table.footer_rows} notes below the table")
    return {
        "file": table.file,
        "sheet": table.sheet,
        "header_row": table.header_row,
        "rows": len(table.df),
        "removed": "; ".join(removed),
        "notes": table.notes[:4],
    }


def build_report(info: RunInfo, tables: dict[str, Table], result: RunResult) -> dict:
    failed = [{"name": c.name, "detail": c.detail} for c in result.checks if c.status == "fail"]
    warned = [{"name": c.name, "detail": c.detail} for c in result.checks if c.status == "warn"]
    warned = [{"name": "Template", "detail": w} for w in info.warnings] + warned
    if info.ai_problem:
        warned.insert(0, {"name": "Qwen not used", "detail": info.ai_problem})
    passed = [{"name": c.name, "detail": c.detail} for c in result.checks if c.status == "pass"]
    status = "fail" if failed else "warn" if warned else "ok"
    plan = info.plan
    return {
        "status": status,
        "status_text": STATUS_TEXT[status],
        "output": info.output,
        "when": info.stamp,
        "template": info.template,
        "instruction": info.instruction,
        "ai": {
            "used": info.ai_used,
            "model": info.ai_model,
            "attempts": info.ai_attempts,
            "tokens": info.prompt_tokens + info.completion_tokens,
            "sample_rows": info.sample_rows,
        },
        "summary": plan.get("summary") or "",
        "assumptions": [str(a) for a in plan.get("assumptions") or []],
        "literals": [f"{c['sheet']}!{c['cell']} = {c['value']}" for c in plan.get("cells") or [] if "value" in c],
        "results": [{"name": s["name"], "rows": len(result.frames[s["frame"]])} for s in plan.get("sheets") or []],
        "failures": failed,
        "warnings": warned,
        "passed": passed[:60],
        "tables": [_table_row(t) for t in tables.values() if not t.hidden],
        "hidden_skipped": sum(1 for t in tables.values() if t.hidden and t.id not in result.used_sources),
        "empty_sheets": info.empty_sheets,
        "ignored": info.ignored,
        "steps": result.lineage[:80],
    }


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def report_markdown(report: dict) -> str:
    ai = report["ai"]
    lines = [
        "# Compile report",
        "",
        f"**Status:** {report['status_text']}",
        f"**File:** `{report['output']}`",
        f"**When:** {report['when']}",
        f"**Template:** {report['template'] or 'None'}",
    ]
    if ai["used"]:
        lines.append(f"**Qwen:** {ai['model']}, {ai['attempts']} tries, {ai['tokens']:,} tokens, {ai['sample_rows']} sample rows per table")
    else:
        lines.append("**Qwen:** Not used")
    if report["instruction"]:
        lines += ["", "**Instruction:**", f"> {_cell(report['instruction'])}"]
    if report["summary"]:
        lines += ["", "## What was done", report["summary"]]
    if report["assumptions"]:
        lines += ["", "## Decisions made", *[f"- {a}" for a in report["assumptions"]]]
    if report["literals"]:
        lines += ["", "## Values typed in directly", *[f"- {v}" for v in report["literals"]]]
    if report["failures"] or report["warnings"]:
        lines += ["", "## Please check"]
        lines += [f"- **{c['name']} (failed):** {c['detail']}" for c in report["failures"]]
        lines += [f"- **{c['name']}:** {c['detail']}" for c in report["warnings"]]
    lines += ["", "## Files read", "", "| File | Sheet | Header row | Data rows | Removed | Notes |", "|---|---|---:|---:|---|---|"]
    for table in report["tables"]:
        lines.append(f"| {_cell(table['file'])} | {_cell(table['sheet'])} | {table['header_row']} | {table['rows']:,} | {_cell(table['removed']) or '-'} | {_cell('; '.join(table['notes'])) or '-'} |")
    if report["hidden_skipped"]:
        lines += ["", f"Hidden sheets skipped: {report['hidden_skipped']}"]
    if report["empty_sheets"]:
        lines += ["", f"Empty sheets: {', '.join(report['empty_sheets'])}"]
    if report["ignored"]:
        lines += ["", f"Not spreadsheets, so ignored: {', '.join(report['ignored'])}"]
    if report["passed"]:
        lines += ["", "## Checks that matched", *[f"- {c['name']}: {c['detail']}" for c in report["passed"]]]
    lines += ["", "## Rows at each step", "", "| Table | Step | Before | After |", "|---|---|---:|---:|"]
    for item in report["steps"]:
        before = "-" if item["rows_in"] is None else f"{item['rows_in']:,}"
        lines.append(f"| {_cell(item['frame'])} | {_cell(item['step'])} | {before} | {item['rows_out']:,} |")
    return "\n".join(lines) + "\n"


def write_reports(info: RunInfo, tables: dict[str, Table], result: RunResult, folder: Path) -> dict:
    report = build_report(info, tables, result)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, default=str), encoding="utf-8")
    (folder / "report.md").write_text(report_markdown(report), encoding="utf-8")
    return report
