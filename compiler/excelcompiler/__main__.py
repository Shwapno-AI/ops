"""Compile one job: read inputs, plan with Qwen, run, write, verify, report.

Exit codes: 0 finished, 1 could not run (the reason is on stderr), 2 finished but a check failed.
The website runs this as a separate process, so one heavy job can never take the site down.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from .engine import Check, RunResult, run_plan
from .errors import CompileError, PlanError
from .heuristics import auto_plan, template_plan
from .plan import validate_against_frames, validate_plan
from .prompts import SYSTEM_PROMPT, shrink_to_fit
from .qwen import QwenClient, QwenError, extract_json
from .reader import Table, build_table, key_overlap, list_input_files, profile_table, read_file
from .report import RunInfo, write_reports
from .template import analyze_template, fill_template, find_template, prepare_template, recalculation_check, verify_template
from .writer import verify_workbook, write_workbook

MAX_PLAN_ATTEMPTS = 3


def stage(name: str) -> None:
    """Progress line the website reads while the job runs."""
    print(f"@@stage {name}", flush=True)


def load_tables(files: list[Path], info: RunInfo) -> tuple[dict[str, Table], dict]:
    tables: dict[str, Table] = {}
    raws: dict = {}
    for path in files:
        try:
            sheets = read_file(path)
        except CompileError as exc:
            info.read_failures.append(str(exc))
            continue
        except Exception as exc:  # a bad file must be reported, never silently skipped
            info.read_failures.append(f"{path.name} could not be read ({type(exc).__name__}: {exc})")
            continue
        for raw in sheets:
            table_id = f"s{len(raws) + 1}"
            table = build_table(raw, table_id)
            raws[table_id] = raw
            if table is None:
                info.empty_sheets.append(f"{raw.file} / {raw.name}")
            else:
                tables[table_id] = table
    return tables, raws


def apply_overrides(plan: dict, tables: dict[str, Table], raws: dict) -> None:
    for override in plan.get("source_overrides") or []:
        table_id = override["source"]
        try:
            table = build_table(raws[table_id], table_id, override["header_row"], override.get("header_depth", 1))
        except ValueError as exc:
            raise PlanError(str(exc)) from None
        if table is None:
            raise PlanError(f"source_overrides: {table_id} has no table at header_row {override['header_row']}")
        tables[table_id] = table


def try_plan(plan: dict, tables: dict[str, Table], raws: dict, sheets: dict | None, instruction: str) -> tuple[RunResult | None, dict, list[str]]:
    """Returns (result, tables used, errors). Tables are copied so a bad override cannot stick."""
    working = dict(tables)
    errors = validate_plan(plan, set(raws), sheets)
    if errors:
        return None, working, errors
    try:
        apply_overrides(plan, working, raws)
        result = run_plan(plan, working, instruction_given=bool(instruction), template_mode=sheets is not None)
    except PlanError as exc:
        return None, working, [str(exc)]
    errors = validate_against_frames(plan, result, sheets)
    return (None if errors else result), working, errors


def plan_with_ai(client: QwenClient, instruction: str, tables, raws, template_info, sample_rows: int, info: RunInfo):
    sheets = template_info.sheets if template_info else None
    profiles = [profile_table(t, sample_rows) for t in tables.values()]
    template_view = template_info.prompt_view(sample_rows) if template_info else None
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": shrink_to_fit(instruction, profiles, template_view, key_overlap(list(tables.values())))},
    ]
    last_errors: list[str] = []
    for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
        info.ai_attempts = attempt
        content = client.chat(messages)
        try:
            plan = extract_json(content)
        except QwenError as exc:
            last_errors = [str(exc)]
        else:
            result, working, last_errors = try_plan(plan, tables, raws, sheets, instruction)
            if result is not None:
                return plan, result, working
        print(f"Qwen plan attempt {attempt} rejected: {last_errors}", flush=True)
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "The plan was rejected:\n- " + "\n- ".join(last_errors) + "\nReturn the corrected full plan as JSON."})
    raise QwenError(f"Qwen could not produce a working plan in {MAX_PLAN_ATTEMPTS} tries. Last problem: {last_errors}")


def _sample_rows() -> int:
    try:
        return max(0, min(20, int(os.getenv("QWEN_SAMPLE_ROWS") or 3)))
    except ValueError:
        return 3


def make_plan(instruction: str, tables, raws, template_info, info: RunInfo):
    client = QwenClient.from_env()
    sample_rows = _sample_rows()
    info.sample_rows = sample_rows
    ai_problem = None
    if client:
        info.ai_model = client.model
        try:
            plan, result, working = plan_with_ai(client, instruction, tables, raws, template_info, sample_rows, info)
            info.ai_used = True
            info.prompt_tokens, info.completion_tokens = client.prompt_tokens, client.completion_tokens
            return plan, result, working
        except QwenError as exc:
            info.prompt_tokens, info.completion_tokens = client.prompt_tokens, client.completion_tokens
            ai_problem = str(exc)
    if instruction:
        reason = ai_problem or "QWEN_API_KEY is not set"
        raise CompileError(f"Your instruction needs Qwen, but it could not be used: {reason}")
    plan = template_plan(tables, template_info.sheets) if template_info else auto_plan(tables)
    info.ai_problem = ai_problem or "QWEN_API_KEY is not set, so tables were combined by matching column names only."
    result, working, errors = try_plan(plan, tables, raws, template_info.sheets if template_info else None, instruction)
    if result is None:
        raise CompileError(f"This could not be compiled without Qwen: {errors}")
    return plan, result, working


def run(args) -> int:
    now = dt.datetime.now(ZoneInfo("Asia/Dhaka"))
    stamp = now.strftime("%Y-%m-%d_%H%M")
    files, ignored = list_input_files(Path(args.input))
    if not files:
        raise CompileError("No Excel or CSV files were found.")

    info = RunInfo(stamp=now.strftime("%d %b %Y, %I:%M %p"), files=[p.name for p in files], ignored=ignored, instruction=args.instruction.strip())
    output_dir = Path(args.output)

    with tempfile.TemporaryDirectory() as work:
        stage("reading")
        template_path = find_template(Path(args.template_dir)) if args.template_dir else None
        template_info = None
        if template_path:
            ready, notes = prepare_template(template_path, Path(work))
            template_info = analyze_template(ready)
            info.template = template_path.name
            info.warnings.extend(notes + template_info.warnings)

        tables, raws = load_tables(files, info)
        if not tables:
            raise CompileError("No table could be read from the files. " + " ".join(info.read_failures))

        stage("planning")
        plan, result, used_tables = make_plan(info.instruction, tables, raws, template_info, info)
        for failure in info.read_failures:
            result.checks.append(Check("File not read", "fail", failure))
        for table_id, table in used_tables.items():
            if table_id not in result.used_sources and len(table.df) and not table.hidden:
                result.check("Not used", "warn", f"{table.file} / {table.sheet} ({len(table.df):,} rows)")

        stage("writing")
        output_dir.mkdir(parents=True, exist_ok=True)
        if template_info:
            suffix = ".xlsm" if template_info.path.suffix.lower() == ".xlsm" else ".xlsx"
            workbook_path = output_dir / f"{template_path.stem}_{stamp}{suffix}"
            audit = fill_template(template_info, plan, result, workbook_path)
            stage("checking")
            verify_template(workbook_path, audit, result)
            recalculation_check(workbook_path, result)
        else:
            workbook_path = output_dir / f"Compiled_{stamp}.xlsx"
            written = write_workbook(plan, result, workbook_path)
            stage("checking")
            verify_workbook(workbook_path, written, result)

        failed = any(c.status == "fail" for c in result.checks)
        if failed:
            flagged = workbook_path.with_name(f"{workbook_path.stem}_CHECK_FAILED{workbook_path.suffix}")
            workbook_path.rename(flagged)
            workbook_path = flagged
        info.output = workbook_path.name
        info.plan = plan
        (output_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        write_reports(info, used_tables, result, output_dir)

    print(f"Output: {workbook_path}")
    return 2 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="excelcompiler", description="Compile Excel files with Qwen's help.")
    parser.add_argument("--input", required=True, help="Folder holding the source files")
    parser.add_argument("--template-dir", default="", help="Folder holding one template file (optional)")
    parser.add_argument("--output", required=True, help="Folder for the result")
    parser.add_argument("--instruction", default="", help="What you want, in any language (optional)")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except CompileError as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
