#!/usr/bin/env python3
"""Store assessment pages: build data/sa.json and data/sa-remarks.json.

Source: the Store Operations Compliance Audit exports in the Store Assessment Drive folder, one
workbook per month (the current month till date). Each workbook has a "Response Summary" sheet
(one row per audit visit: date, time, outlet, auditor, total score out of 290) and an "Answer
Details" sheet (one row per question answered). Sheets and files are recognised by their columns,
never by name, and the month comes from the audit dates, so a replaced file replaces its month
and a new file adds one.

The workbooks are large (about 100 MB each), so a file whose Drive id and modified time have not
changed is not downloaded again: its audits are reused from the previous sa.json.

Output:
  sa.json          questions, categories, auditors, months and every audit visit with its
                   question scores (compact arrays)
  sa-remarks.json  the auditors' remarks per visit, loaded only when an outlet is opened

Environment:
  SA_FOLDER_ID  Drive folder (default: Store Assessment)
  SA_OUT        output file (default: data/sa.json)
  DATA_OUT      data.json with the outlet master (default: data/data.json)
  DRIVE_CACHE   shared download cache (see scripts/network/fetch_drive_data.py)
Usage: python scripts/sa/refresh.py [--local DIR]   # DIR of .xlsx files instead of Drive
"""
import datetime as dt
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "sku"))
sys.path.insert(0, str(HERE.parent / "network"))
import xlsx_stream  # noqa: E402

FOLDER = (os.environ.get("SA_FOLDER_ID") or "1TJ_c7VVyg6Qa_o0c62_LsZkd0sBHDEHF").strip()
OUT = Path(os.environ.get("SA_OUT") or ROOT / "data" / "sa.json")
OUT_REM = OUT.with_name("sa-remarks.json")
MASTER = Path(os.environ.get("DATA_OUT") or ROOT / "data" / "data.json")


def log(msg):
    print(msg, flush=True)


def key(v):
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


SUMMARY = {"rid": "response id", "date": "date", "time": "time", "total": "total score", "possible": "total possible score",
           "site": "site code", "user": "created by user id", "answered": "number of questions answered", "questions": "total questions"}
ANSWERS = {"rid": "response id", "qid": "question id", "title": "question title", "cat": "question category", "type": "question type",
           "max": "question max score", "answer": "user answer", "score": "answer score", "text": "text answer"}


def header_map(row, want):
    h = [key(x) for x in row or []]
    m = {k: h.index(v) for k, v in want.items() if v in h}
    return m if len(m) == len(want) else None


def num(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "", "N/A") else None
    except ValueError:
        return None


def iso_date(v):
    """'8/1/2026' or '8/1/2026, 12:36:01 PM' (or an Excel serial) -> '2026-08-01'."""
    if isinstance(v, float):
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""


def hhmm(v):
    m = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AP]M)?", str(v or ""), re.I)
    if not m:
        return ""
    h = int(m.group(1)) % 12 + (12 if (m.group(3) or "").upper() == "PM" else 0) if m.group(3) else int(m.group(1))
    return f"{h:02d}:{m.group(2)}"


def read_workbook(path):
    """Returns (visits {rid: {...}}, answers [(rid, qid, title, cat, type, max, answer, score, text)]) or None."""
    with __import__("zipfile").ZipFile(path) as z:
        sheets = xlsx_stream._sheets(z)
    summ = ans = None
    for i in range(len(sheets)):
        first = next(xlsx_stream.rows(path, i), None)
        if summ is None and header_map(first, SUMMARY):
            summ = (i, header_map(first, SUMMARY))
        elif ans is None and header_map(first, ANSWERS):
            ans = (i, header_map(first, ANSWERS))
    if not summ or not ans:
        return None
    visits = {}
    it = xlsx_stream.rows(path, summ[0]); next(it, None)
    hm = summ[1]
    for r in it:
        g = lambda k: r[hm[k]] if hm[k] < len(r) else None  # noqa: E731
        rid = num(g("rid"))
        if rid is None:
            continue
        visits[int(rid)] = {"date": iso_date(g("date")), "time": hhmm(g("time")), "site": str(g("site") or "").strip().upper(),
                            "user": str(g("user") or "").strip(), "total": num(g("total")), "possible": num(g("possible")),
                            "answered": num(g("answered")), "questions": num(g("questions"))}
    answers = []
    it = xlsx_stream.rows(path, ans[0]); next(it, None)
    hm = ans[1]
    for r in it:
        g = lambda k: r[hm[k]] if hm[k] < len(r) else None  # noqa: E731
        rid, qid = num(g("rid")), num(g("qid"))
        if rid is None or qid is None:
            continue
        answers.append((int(rid), int(qid), str(g("title") or "").strip(), str(g("cat") or "").strip(), str(g("type") or "").strip().lower(),
                        num(g("max")) or 0.0, str(g("answer") or "").strip(), num(g("score")), str(g("text") or "").strip()))
    return visits, answers


def modified_iso(text):
    import fetch_drive_data as drive
    ts = drive.modified_sort_key({"modified": text})
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() if ts else ""


def main():
    local = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        old_rem = json.loads(OUT_REM.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old, old_rem = {}, {}
    try:
        md = json.loads(MASTER.read_text(encoding="utf-8"))
        master = {o["c"] for o in ((md.get("master") or {}).get("outlets") or [])}
    except (OSError, ValueError):
        master = set()

    if local:
        items = [{"id": p.name, "name": p.name, "modified": str(int(p.stat().st_mtime)), "path": str(p)} for p in sorted(Path(local).glob("*.xlsx"))]
    else:
        import fetch_drive_data as drive
        log(f"Listing Drive folder {FOLDER}…")
        items = [i for i in drive.walk(FOLDER) if drive.is_spreadsheet(i)]
    if not items:
        log("::warning::No workbooks in the Store Assessment folder; sa.json left as is.")
        return 1

    # Reuse what an unchanged file gave last time (matched by Drive id + modified time). Drive lists today's
    # files with a time ("2:27 am") and older ones with a date ("Sep 29"); that change alone is not an update.
    prev_files = {f["key"]: (n, f) for n, f in enumerate((old.get("source") or {}).get("files") or []) if f.get("key")}
    by_id = {f["key"].split("|")[0]: f["key"] for f in (old.get("source") or {}).get("files") or [] if f.get("key")}
    is_time = lambda t: bool(re.match(r"^\d{1,2}:\d{2}\s*[ap]m$", str(t or "").strip(), re.I))  # noqa: E731
    def same_file(item):
        k = by_id.get(item["id"])
        if not k:
            return None
        f = prev_files[k][1]
        if f.get("modified") == item.get("modified"):
            return k
        if not local and is_time(f.get("modified")) and not is_time(item.get("modified")) and f.get("modifiedIso") and f["modifiedIso"] == modified_iso(item.get("modified", "")):
            return k
        return None
    oq = {q[0]: q for q in old.get("questions") or []}
    per_file = []  # (file meta, visits {rid: visit}, answers list or None, reused rows or None)
    with tempfile.TemporaryDirectory(prefix="sa-") as work:
        for item in items:
            fkey = f"{item['id']}|{item.get('modified', '')}"
            meta = {"key": fkey, "name": item.get("path") or item["name"], "modified": item.get("modified", ""), "modifiedIso": "" if local else modified_iso(item.get("modified", ""))}
            pk = same_file(item) if old.get("schema") == 1 else None
            if pk:
                n, f = prev_files[pk]
                rows = [v for v in old.get("visits") or [] if v[1] == n]
                if rows:
                    meta.update({"key": pk, "modified": f.get("modified", meta["modified"]), "modifiedIso": f.get("modifiedIso") or meta["modifiedIso"]})
                    per_file.append((meta, None, None, rows))
                    log(f"  keep  {meta['name']}: {len(rows)} audits (unchanged)")
                    continue
            if local:
                path = item["path"]
            else:
                path = Path(work) / "wb.xlsx"
                try:
                    path.write_bytes(drive.fetch_bytes(item))
                except Exception as err:  # noqa: BLE001
                    log(f"::warning::{meta['name']}: {err}")
                    continue
            try:
                got = read_workbook(path)
            except Exception as err:  # noqa: BLE001 - not a readable workbook
                got = None
                log(f"  skip  {meta['name']} ({err})")
            if not got:
                log(f"  skip  {meta['name']}  (not a store assessment export)")
                continue
            per_file.append((meta, got[0], got[1], None))
            log(f"  read  {meta['name']}: {len(got[0])} audits, {len(got[1])} answers")
    if not per_file:
        log("::error::No store assessment workbooks found; sa.json left as is.")
        return 1

    # Questions and categories (in question-id order), from the new answers plus the previous file.
    qinfo = {}
    for qid, q in oq.items():
        qinfo[qid] = {"cat": old["cats"][q[1]], "title": q[2], "type": q[3], "max": q[4]}
    for rq in old.get("remarkQs") or []:
        qinfo[rq[0]] = {"cat": old["cats"][rq[1]], "title": "Remarks", "type": "text", "max": 0}
    for _, _, answers, _ in per_file:
        for rid, qid, title, cat, typ, mx, *_ in answers or []:
            qinfo[qid] = {"cat": cat, "title": title, "type": typ, "max": mx}
    order = sorted(qinfo)
    cats = []
    for q in order:
        if qinfo[q]["cat"] not in cats:
            cats.append(qinfo[q]["cat"])
    scored = [q for q in order if qinfo[q]["type"] != "text" and qinfo[q]["max"] > 0]
    remark_qs = [q for q in order if qinfo[q]["type"] == "text"]
    qpos = {q: i for i, q in enumerate(scored)}

    # Visits: newer files win when the same audit appears twice.
    auditors, aidx = [], {}
    def auditor(name):
        if name not in aidx:
            aidx[name] = len(auditors)
            auditors.append(name)
        return aidx[name]
    per_file.sort(key=lambda x: x[0]["modifiedIso"] or x[0]["modified"])
    visits, remarks, files_meta = {}, {}, []
    for fn, (meta, vmap, answers, reused) in enumerate(per_file):
        meta = dict(meta)
        if reused is not None:
            oldq = [q[0] for q in old.get("questions") or []]
            for v in reused:
                rid = v[0]
                qs = [None] * len(scored)
                for q, s in zip(oldq, v[9]):
                    if q in qpos:
                        qs[qpos[q]] = s
                visits[rid] = [rid, fn, v[2], v[3], v[4], auditor(old["auditors"][v[5]]), v[6], v[7], v[8], qs]
                if str(rid) in old_rem:
                    remarks[str(rid)] = old_rem[str(rid)]
        else:
            qs_by = defaultdict(lambda: [None] * len(scored))
            for rid, qid, title, cat, typ, mx, answer, score, text in answers:
                if qid in qpos:
                    qs_by[rid][qpos[qid]] = score if score is not None else (0.0 if answer and answer != "No Answer" else None)
                elif typ == "text":
                    t = text if text and text != "N/A" else answer
                    if t and t not in ("No Answer", "N/A", ".", "-"):
                        remarks.setdefault(str(rid), []).append([cats.index(cat) if cat in cats else 0, t[:600]])
            for rid, v in vmap.items():
                if not v["date"] or not v["site"]:
                    continue
                visits[rid] = [rid, fn, v["date"], v["time"], v["site"], auditor(v["user"]), v["total"], v["possible"], v["answered"], qs_by.get(rid, [None] * len(scored))]
        meta["audits"] = sum(1 for v in visits.values() if v[1] == fn)
        files_meta.append(meta)
    vis = sorted(visits.values(), key=lambda v: (v[2], v[3], v[0]))
    # tidy numbers: whole points where possible
    for v in vis:
        v[6:9] = [None if x is None else (int(x) if float(x).is_integer() else round(x, 2)) for x in v[6:9]]
        v[9] = [None if x is None else (int(x) if float(x).is_integer() else round(x, 2)) for x in v[9]]
    for fn, meta in enumerate(files_meta):
        ms = sorted({v[2][:7] for v in vis if v[1] == fn})
        meta["months"] = ms
    months = []
    for m in sorted({v[2][:7] for v in vis}):
        ds = [v[2] for v in vis if v[2].startswith(m)]
        months.append({"m": m, "start": min(ds), "end": max(ds), "audits": len(ds), "outlets": len({v[4] for v in vis if v[2].startswith(m)})})

    # Data checks for the Data quality page.
    issues = []
    for mo in months:
        mv = [v for v in vis if v[2].startswith(mo["m"])]
        unknown = sorted({v[4] for v in mv} - master) if master else []
        if unknown:
            issues.append({"level": "warn", "message": f"{mo['m']}: {len(unknown)} outlet codes audited but not in the outlet master: {', '.join(unknown[:12])}{' …' if len(unknown) > 12 else ''}"})
        many = [(c, n) for c, n in Counter(v[4] for v in mv).most_common() if n >= 10]
        if many:
            issues.append({"level": "info", "message": f"{mo['m']}: {len(many)} outlets audited 10 or more times, e.g. " + ", ".join(f"{c} ({n})" for c, n in many[:6])})
        part = sum(1 for v in mv if v[8] is not None and v[8] < len(scored))
        if part:
            issues.append({"level": "info", "message": f"{mo['m']}: {part} audits left scored questions unanswered; they are still scored out of {int(sum(qinfo[q]['max'] for q in scored))}, as in the export."})

    payload = {
        "schema": 1, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {"folder": FOLDER, "files": files_meta},
        "cats": cats,
        # [question id, category index, title, type, max score]
        "questions": [[q, cats.index(qinfo[q]["cat"]), qinfo[q]["title"], qinfo[q]["type"], qinfo[q]["max"]] for q in scored],
        "remarkQs": [[q, cats.index(qinfo[q]["cat"])] for q in remark_qs],
        "maxScore": sum(qinfo[q]["max"] for q in scored),
        "auditors": auditors,
        "months": months,
        # [response id, file index, date, time, outlet code, auditor index, total score, possible score, questions answered, [question scores]]
        "visits": vis,
        "issues": issues,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for path, data in ((OUT_REM, remarks), (OUT, payload)):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(vis)} audits, {len(months)} months, {len(scored)} questions, {len(auditors)} auditors; remarks {OUT_REM.stat().st_size // 1024} KB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
