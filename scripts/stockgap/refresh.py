#!/usr/bin/env python3
"""Stock gap (inventory counting gap) page: build data/stockgap.json.

Source: the "Stock Gap Dashboard" workbook (cumulative, e.g. "Stock Gap Dashboard Till AUG'26.xlsx")
anywhere under the dashboard's mother Drive folder. Only workbooks whose name mentions a stock or counting
gap are opened, and the one used must have a RawData sheet with these columns: Site, Cat Name,
Net (PHY-SAP) Value, Sales, Month Of Inventory (Site Name, Outlet Type and Zonal are read when present).
Each RawData row is one outlet x counting month x category. The newest such workbook (by its last month,
then Drive date) is used.

The counting gap of a scope and month is minus the sum of "Net (PHY-SAP) Value" (a shortage is a positive
gap), and the gap % on sales divides it by the sales of the rows counted: the same rules as the
workbook's Top View sheet. Category spellings that differ only in case, plus "Madeicine", are merged.

The workbook is about 20 MB, so an unchanged file (same Drive id and modified time) is not parsed again.

Output data/stockgap.json:
  months  ["2022-01", ...]          cats  [category, ...]
  sites   [[code, name, outlet type, zonal], ...]
  r       {s: [site index], m: [month index], c: [category index], n: [net PHY-SAP, taka], v: [sales, taka]}

Environment:
  SG_FOLDER_ID  Drive folder to search (default: the mother folder, DATA_FOLDER_ID)
  SG_OUT        output file (default: data/stockgap.json)
  DRIVE_CACHE   shared download cache (see scripts/network/fetch_drive_data.py)
Usage: python scripts/stockgap/refresh.py [--local FILE.xlsx]
"""
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "network"))

FOLDER = (os.environ.get("SG_FOLDER_ID") or os.environ.get("DATA_FOLDER_ID") or "1Te9stxbcBsIIO8bNElPuDXXPovkk4v1l").strip()
OUT = Path(os.environ.get("SG_OUT") or ROOT / "data" / "stockgap.json")
NAME_RE = re.compile(r"stock\s*gap|counting\s*gap|inventory\s*gap", re.I)
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
NEED = {"site": "site", "cat": "cat name", "net": "net (phy-sap) value", "sales": "sales", "month": "month of inventory"}
OPTIONAL = {"name": "site name", "type": "outlet type", "zonal": "zonal"}
CAT_FIX = {"madeicine": "Medicine"}


def log(msg):
    print(msg, flush=True)


def key(v):
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def month(v):
    """"Jan'22", "June'22", "Sept'23", a date -> "2022-01"."""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m")
    m = re.match(r"\s*([a-z]{3})[a-z]*\.?\s*['’\-\s]?\s*(\d{2}|\d{4})\s*$", str(v or ""), re.I)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    y = int(m.group(2))
    return f"{y + 2000 if y < 100 else y}-{MONTHS[m.group(1).lower()]:02d}"


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def read_workbook(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = next((w for w in wb.worksheets if w.title.strip().lower() == "rawdata"), None)
        sheets = [ws] if ws is not None else wb.worksheets
        for ws in sheets:
            it = ws.iter_rows(values_only=True)
            head = next(it, None) or []
            h = [key(x) for x in head]
            if not all(v in h for v in NEED.values()):
                continue
            ix = {k: h.index(v) for k, v in NEED.items()}
            ix.update({k: h.index(v) for k, v in OPTIONAL.items() if v in h})
            sites, site_ix, cats, cat_ix, cat_name, months = [], {}, [], {}, {}, set()
            rows = []
            for r in it:
                g = lambda k: r[ix[k]] if k in ix and ix[k] < len(r) else None  # noqa: E731
                code = str(g("site") or "").strip().upper()
                m = month(g("month"))
                cat = re.sub(r"\s+", " ", str(g("cat") or "")).strip()
                if not code or not m or not cat:
                    continue
                ck = CAT_FIX.get(cat.lower(), cat).lower()
                if ck not in cat_ix:
                    cat_ix[ck] = len(cats)
                    cats.append({})
                spelled = cats[cat_ix[ck]]
                spelled[CAT_FIX.get(cat.lower(), cat)] = spelled.get(CAT_FIX.get(cat.lower(), cat), 0) + 1
                if code not in site_ix:
                    site_ix[code] = len(sites)
                    sites.append([code, str(g("name") or "").strip(), str(g("type") or "").strip(), str(g("zonal") or "").strip()])
                months.add(m)
                rows.append((site_ix[code], m, cat_ix[ck], num(g("net")), num(g("sales"))))
            if rows:
                # each category under its most used spelling ("Home & Garden" over "Home & garden")
                names = [max(v.items(), key=lambda kv: kv[1])[0] for v in cats]
                return {"sheet": ws.title, "sites": sites, "cats": names, "months": sorted(months), "rows": rows}
        return None
    finally:
        wb.close()


def main():
    local = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    if local:
        p = Path(local)
        items = [{"id": p.name, "name": p.name, "path": str(p), "modified": str(int(p.stat().st_mtime))}]
    else:
        import fetch_drive_data as drive
        log(f"Listing Drive folder {FOLDER}…")
        items = [i for i in drive.walk(FOLDER) if drive.is_spreadsheet(i) and NAME_RE.search(i["name"])]
    if not items:
        log("No stock gap workbook in the Drive folder; stockgap.json left as is.")
        return 0
    # newest first by Drive date; an unchanged file is not parsed again
    items.sort(key=lambda i: (0 if local else drive.modified_sort_key(i)), reverse=True)
    best = None
    with tempfile.TemporaryDirectory(prefix="sg-") as work:
        for item in items:
            fkey = f"{item['id']}|{item.get('modified', '')}"
            if (old.get("source") or {}).get("key") == fkey and old.get("schema") == 1:
                log(f"  keep  {item['name']} (unchanged)")
                return 0
            path = item.get("path") or str(Path(work) / "sg.xlsx")
            if not item.get("path"):
                try:
                    Path(path).write_bytes(drive.fetch_bytes(item))
                except Exception as err:  # noqa: BLE001
                    log(f"::warning::{item['name']}: {err}")
                    continue
            try:
                got = read_workbook(path)
            except Exception as err:  # noqa: BLE001 - not a readable workbook
                log(f"  skip  {item['name']} ({err})")
                continue
            if not got:
                log(f"  skip  {item['name']} (no RawData sheet with the stock gap columns)")
                continue
            log(f"  found {item['name']}: {len(got['rows'])} rows, {len(got['sites'])} outlets, {got['months'][0]} to {got['months'][-1]}")
            best = (item, fkey, got)
            break
    if not best:
        log("::warning::No readable stock gap workbook; stockgap.json left as is.")
        return 1
    item, fkey, got = best
    mi = {m: i for i, m in enumerate(got["months"])}
    rows = got["rows"]
    payload = {
        "schema": 1, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {"key": fkey, "file": item["name"], "modified": item.get("modified", ""), "sheet": got["sheet"], "rows": len(rows)},
        "months": got["months"], "cats": got["cats"], "sites": got["sites"],
        # one entry per RawData row: site, month, category, net (PHY-SAP) value and sales, in whole taka
        "r": {"s": [r[0] for r in rows], "m": [mi[r[1]] for r in rows], "c": [r[2] for r in rows],
              "n": [round(r[3]) for r in rows], "v": [round(r[4]) for r in rows]},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT)
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(rows)} rows, {len(got['sites'])} outlets, {len(got['cats'])} categories, "
        f"{got['months'][0]} to {got['months'][-1]}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
