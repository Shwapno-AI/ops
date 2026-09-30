#!/usr/bin/env python3
"""Credit card extra cost and visit compliance: build data/ccv.json.

Source: the "Dashboard Raw Data" Drive folder (Credit Card and Visit Compliance). Files are recognised
by their columns, and each period comes from the dates in the file name (…_2026-09-01_to_2026-09-27):
  credit card   CSV  Outlet Code, Outlet Name, Regional Head, Zonal, one column per provider (Bkash,
                     City, EBL, …), Total: the extra card cost per outlet over the period
  attendance    CSV  Date (dd-mm-yy), Employee Code, Punched Device (outlet codes, comma separated),
                     Status: the visit team's punches, one row per person and day
  visit plan    XLSX sheets for zonals and regional heads: CODE, Outlet Name, a name column, then one
                     column per day of the month holding Yes (visit planned) or No
The newest file of each kind is used (latest period end). Only workbooks whose name mentions a visit
or schedule are downloaded; the folder also holds the Store Assessment audit export (about 100 MB),
which scripts/sa/refresh.py reads from its own folder.

Output data/ccv.json:
  cc     {from, to, providers, rows: [[outlet code, [amount per provider], total]]}
  visit  {from, to, people, rows: [[outlet code, planned days, planned days with a punch, days with a punch]]}
         planned days count the zonal and regional head plans together (a day planned by both counts
         once), up to the last attendance day; a punch is any visit-team punch at the outlet that day.

Environment:
  CCV_FOLDER_ID  Drive folder (default: Dashboard Raw Data)
  CCV_OUT        output file (default: data/ccv.json)
  DRIVE_CACHE    shared download cache (see scripts/network/fetch_drive_data.py)
Usage: python scripts/ccv/refresh.py [--local DIR]   # DIR of .csv/.xlsx files instead of Drive
"""
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "network"))

FOLDER = (os.environ.get("CCV_FOLDER_ID") or "16HTr8nfPz4P2PMr4QB0bjgwiD110Qd-0").strip()
OUT = Path(os.environ.get("CCV_OUT") or ROOT / "data" / "ccv.json")
OUTLET_RE = re.compile(r"^[A-Z]{1,3}\d{2,4}$")


def log(msg):
    print(msg, flush=True)


def key(v):
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


def num(v):
    try:
        return float(str(v).replace(",", "")) if str(v or "").strip() not in ("", "N/A", "-") else 0.0
    except ValueError:
        return 0.0


def period(name):
    """'ccol_outlets_2026-09-01_to_2026-09-27.csv' -> ('2026-09-01', '2026-09-27')."""
    d = re.findall(r"(20\d\d)-(\d\d)-(\d\d)", name)
    return (f"{d[0][0]}-{d[0][1]}-{d[0][2]}", f"{d[-1][0]}-{d[-1][1]}-{d[-1][2]}") if d else ("", "")


def day(v):
    """'01-09-26' (dd-mm-yy), '2026-09-01', a date or datetime -> '2026-09-01'."""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v or "").strip()
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$", s)
    if m:
        y = int(m.group(3))
        return f"{y + 2000 if y < 100 else y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else ""


def read_csv(body):
    text = body.decode("utf-8-sig", "replace")
    return list(csv.reader(io.StringIO(text)))


def as_cc(rows):
    h = [key(x) for x in rows[0]] if rows else []
    if not {"outlet code", "total"} <= set(h):
        return None
    ci, ti = h.index("outlet code"), h.index("total")
    skip = {"outlet code", "outlet name", "regional head", "zonal", "total", "zone", "region"}
    prov = [i for i, k in enumerate(h) if k not in skip and i != ti]
    out = []
    for r in rows[1:]:
        code = (r[ci] if ci < len(r) else "").strip().upper()
        if not OUTLET_RE.match(code):  # blank lines and the closing "TOTAL (1005)" row
            continue
        amounts = [round(num(r[i]) if i < len(r) else 0.0, 2) for i in prov]
        out.append([code, amounts, round(num(r[ti]) if ti < len(r) else sum(amounts), 2)])
    return {"providers": [rows[0][i].strip() for i in prov], "rows": out}


def as_attendance(rows):
    h = [key(x) for x in rows[0]] if rows else []
    if not {"date", "employee code", "punched device"} <= set(h):
        return None
    di, ei, pi = h.index("date"), h.index("employee code"), h.index("punched device")
    punches, people = {}, set()
    for r in rows[1:]:
        d = day(r[di] if di < len(r) else "")
        if not d:
            continue
        # outlet codes only: an absent day lists "N/A"
        codes = [c for c in (x.strip().upper() for x in (r[pi] if pi < len(r) else "").split(",")) if OUTLET_RE.match(c)]
        if codes:
            people.add((r[ei] if ei < len(r) else "").strip())
        for c in codes:
            punches.setdefault(c, set()).add(d)
    days = sorted({d for s in punches.values() for d in s}) or sorted({day(r[di]) for r in rows[1:] if di < len(r) and day(r[di])})
    return {"punches": punches, "people": len(people - {""}), "days": days}


def as_plan(path):
    """Workbook with one sheet per role: CODE, …, then one Yes/No column per date."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    plan, sheets = {}, []
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        head = next(it, None) or []
        h = [key(x) for x in head]
        if "code" not in h:
            continue
        ci = h.index("code")
        dcols = [(i, day(v)) for i, v in enumerate(head) if day(v)]
        if len(dcols) < 7:
            continue
        sheets.append(ws.title)
        for r in it:
            code = str(r[ci] or "").strip().upper() if ci < len(r) else ""
            if not code:
                continue
            for i, d in dcols:
                if i < len(r) and str(r[i] or "").strip().lower() in ("yes", "y", "1", "true"):
                    plan.setdefault(code, set()).add(d)
    wb.close()
    if not sheets:
        return None
    return {"plan": plan, "sheets": sheets, "month": min(d for _, d in dcols)[:7] if dcols else ""}


def main():
    local = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None
    if local:
        items = [{"id": p.name, "name": p.name, "modified": str(int(p.stat().st_mtime)), "path": str(p)} for p in sorted(Path(local).iterdir()) if p.is_file()]
        fetch = lambda item: Path(item["path"]).read_bytes()  # noqa: E731
    else:
        import fetch_drive_data as drive
        log(f"Listing Drive folder {FOLDER}…")
        items = drive.walk(FOLDER)
        fetch = drive.fetch_bytes
    cc, att, plan = [], [], []
    with tempfile.TemporaryDirectory(prefix="ccv-") as work:
        for item in items:
            name = item["name"]
            low = name.lower()
            if low.startswith("~$"):
                continue
            meta = {"name": item.get("path") or name, "modified": item.get("modified", "")}
            try:
                if low.endswith(".csv"):
                    rows = read_csv(fetch(item))
                    got = as_cc(rows)
                    if got:
                        cc.append((period(name), meta, got))
                        log(f"  credit card  {name}: {len(got['rows'])} outlets, providers {', '.join(got['providers'])}")
                        continue
                    got = as_attendance(rows)
                    if got:
                        att.append((period(name), meta, got))
                        log(f"  attendance   {name}: {got['people']} people, {len(got['punches'])} outlets punched")
                        continue
                    log(f"  skip  {name} (columns not recognised)")
                elif low.endswith((".xlsx", ".xlsm")) and re.search(r"visit|schedule", low):
                    path = Path(work) / "plan.xlsx"
                    path.write_bytes(fetch(item))
                    got = as_plan(path)
                    if got:
                        plan.append(((got["month"], got["month"]), meta, got))
                        log(f"  visit plan   {name}: sheets {', '.join(got['sheets'])}, {len(got['plan'])} outlets, {got['month']}")
                    else:
                        log(f"  skip  {name} (no plan sheet)")
            except Exception as err:  # noqa: BLE001 - one unreadable file must not stop the rest
                log(f"::warning::{name}: {err}")
    if not cc and not att:
        log("::warning::No credit card or attendance file found; ccv.json left as is.")
        return 1

    payload = {"schema": 1, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "source": {"folder": FOLDER, "files": []}}
    if cc:
        (f, t), meta, got = max(cc, key=lambda x: (x[0][1], x[1]["name"]))
        payload["cc"] = {"from": f, "to": t, "providers": got["providers"], "rows": got["rows"]}
        payload["source"]["files"].append({**meta, "role": "credit card"})
    if att:
        (f, t), meta, got = max(att, key=lambda x: (x[0][1], x[1]["name"]))
        days = got["days"]
        first, last = f or (days[0] if days else ""), min(t or "9999", days[-1] if days else "9999")
        punches = got["punches"]
        month = (first or last)[:7]
        pl = next((p for p in sorted(plan, key=lambda x: x[0][0], reverse=True) if p[0][0] == month), None)
        planned = {c: {d for d in ds if first <= d <= last} for c, ds in (pl[2]["plan"] if pl else {}).items()}
        rows = []
        for c in sorted(set(planned) | set(punches)):
            pd, vd = planned.get(c, set()), {d for d in punches.get(c, set()) if first <= d <= last}
            rows.append([c, len(pd), len(pd & vd), len(vd)])
        payload["visit"] = {"from": first, "to": last, "people": got["people"], "planned": bool(pl), "rows": rows}
        payload["source"]["files"].append({**meta, "role": "attendance"})
        if pl:
            payload["source"]["files"].append({**pl[1], "role": "visit plan"})
        else:
            log(f"::warning::No visit plan for {month}; planned visits are left out.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT)
    v = payload.get("visit") or {}
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): credit card {len((payload.get('cc') or {}).get('rows') or [])} outlets; "
        f"visits {v.get('from', '')} to {v.get('to', '')}, {len(v.get('rows') or [])} outlets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
