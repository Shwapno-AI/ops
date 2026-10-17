#!/usr/bin/env python3
"""Z - REPORT page (Store level report): build data/zr.json and one file per outlet in data/zr/.

Source: the Z-Report workbook ("Z-REPORT CATEGORY WISE SALES …") in the Z-Report Drive folder. The file
name can change; the workbook is recognised by its sheets and headers, as in the zreport-dual-dashboard:

  MAIN                         row 2 has Code, Month and Name; one row per outlet and month with each
                               category's Sales and FootFall. Rows whose Code starts with "All:" are the
                               workbook's all-outlet month summaries (Name = number of outlets).
  All Year                     row 2 = months, row 3 = SALES / FF / Basket blocks, column B = row labels.
                               A row whose Sales and FF formulas read one MAIN column each (SUMIFS(MAIN!$H:$H …))
                               is a category; any other row is a group / total of the rows its formula names.
  AUTOMATED PROJECTED ZREPORT  column A = row labels of the projection table, column B formulas = its totals.

Only the categories, the row structure and the numbers are taken; the page works out Basket, the totals and
the projection (see pageZR in assets/app.js). An unchanged workbook (same Drive id and modified time) is not
downloaded again.

Output:
  zr.json      meta, months, All Year rows, projection rows, network totals, all-outlet month summaries,
               outlets [[code, name, file, last month with data]]
  zr/<code>.json  {code, name, months: {"YYYY-MM": [[sales by category], [footfall by category]]}}

Environment:
  ZR_FOLDER_ID  Drive folder (default: Z-Report)
  ZR_OUT        output file (default: data/zr.json); the outlet files go in a "zr" folder beside it
  DRIVE_CACHE   shared download cache (see scripts/network/fetch_drive_data.py)
Usage: python scripts/zr/refresh.py [--local FILE.xlsx]
"""
import datetime as dt
import json
import math
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from posixpath import normpath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "network"))

FOLDER = (os.environ.get("ZR_FOLDER_ID") or "1oRRVEZ7A6AjrsXZ-wHx7JQrDh3FoB2eb").strip()
OUT = Path(os.environ.get("ZR_OUT") or ROOT / "data" / "zr.json")
OUT_DIR = OUT.with_suffix("")  # data/zr/
SCHEMA = 2  # a new schema rebuilds even when the workbook is unchanged
SHEETS = ("MAIN", "All Year", "AUTOMATED PROJECTED ZREPORT")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PREL = "http://schemas.openxmlformats.org/package/2006/relationships"
MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def log(msg):
    print(msg, flush=True)


def norm(v):
    return re.sub(r"\s+", " ", str(v or "").strip()).casefold()


def col_num(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    n = 0
    for ch in m.group(1) if m else "":
        n = n * 26 + ord(ch) - 64
    return n


def month_key(v):
    text = str(v or "").strip()
    if not text:
        return None
    m = re.match(r"^([A-Za-z]{3})[-\s/](\d{2}|\d{4})$", text)
    if m and m.group(1).lower() in MON:
        y = int(m.group(2))
        if len(m.group(2)) == 2:
            y += 2000 if y < 80 else 1900
        return f"{y:04d}-{MON[m.group(1).lower()]:02d}"
    for fmt in ("%Y-%m", "%Y/%m", "%b-%Y", "%b %Y", "%Y-%m-%d", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    try:  # Excel serial date
        serial = float(text)
        if serial > 20000:
            return (dt.datetime(1899, 12, 30) + dt.timedelta(days=serial)).strftime("%Y-%m")
    except ValueError:
        pass
    return None


def number(v):
    try:
        n = float(str(v or "").strip() or 0)
        return n if math.isfinite(n) else 0.0
    except ValueError:
        return 0.0


def summary_row(code, month):
    """The workbook's all-outlet month rows ("All:Jan-21"), kept apart from the outlets."""
    c = str(code or "").strip().lower()
    if c.startswith("all:"):
        return True
    return (c.startswith("all ") or c.startswith("all -")) and bool(month_key(c.split(":")[-1].strip()) or month_key(month))


class Xlsx:
    """Streams rows with values and formulas (formulas carry the category mapping)."""

    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        names = self.z.namelist()
        self.shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(self.z.read("xl/sharedStrings.xml"))
            self.shared = ["".join(t.text or "" for t in si.iter(f"{{{NS}}}t")) for si in root.findall(f"{{{NS}}}si")]
        wb = ET.fromstring(self.z.read("xl/workbook.xml"))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(self.z.read("xl/_rels/workbook.xml.rels")).findall(f"{{{PREL}}}Relationship")}
        self.sheets = {}
        node = wb.find(f"{{{NS}}}sheets")
        for s in node if node is not None else []:
            rid = s.attrib.get(f"{{{OREL}}}id")
            if rid in rels:
                t = rels[rid].lstrip("/")
                self.sheets[norm(s.attrib.get("name"))] = normpath(t if t.startswith("xl/") else "xl/" + t)

    def close(self):
        self.z.close()

    def has(self, names):
        return all(norm(n) in self.sheets for n in names)

    def rows(self, sheet):
        with self.z.open(self.sheets[norm(sheet)]) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag != f"{{{NS}}}row":
                    continue
                row = {}
                for c in el.findall(f"{{{NS}}}c"):
                    i = col_num(c.attrib.get("r", ""))
                    if not i:
                        continue
                    t, f = c.attrib.get("t"), c.find(f"{{{NS}}}f")
                    if t == "inlineStr":
                        node = c.find(f"{{{NS}}}is")
                        v = "".join(x.text or "" for x in node.iter(f"{{{NS}}}t")) if node is not None else ""
                    else:
                        node = c.find(f"{{{NS}}}v")
                        v = node.text or "" if node is not None else ""
                        if t == "s" and v:
                            v = self.shared[int(v)] if int(v) < len(self.shared) else v
                    row[i] = (v, (f.text or "") if f is not None else "")
                yield int(el.attrib.get("r", "0")), row
                el.clear()

    def head(self, sheet, last):
        out = {}
        for rn, row in self.rows(sheet):
            if rn > last:
                break
            out[rn] = row
        return out


val = lambda row, c: row.get(c, ("", ""))[0]  # noqa: E731
formula = lambda row, c: row.get(c, ("", ""))[1]  # noqa: E731


def main_col(f):
    m = re.search(r"MAIN!\$([A-Z]+):\$([A-Z]+)", f or "", re.I)
    return col_num(m.group(1).upper()) if m and m.group(1).upper() == m.group(2).upper() else None


def dep_rows(f):
    f, deps = f or "", []
    for m in re.finditer(r"\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)", f, re.I):
        if m.group(1).upper() == m.group(3).upper():
            a, b = int(m.group(2)), int(m.group(4))
            deps += range(a, b + (1 if a <= b else -1), 1 if a <= b else -1)
    for m in re.finditer(r"\$?[A-Z]+\$?(\d+)", re.sub(r"\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+", "", f, flags=re.I), re.I):
        deps.append(int(m.group(1)))
    return list(dict.fromkeys(deps))


def check(x):
    """Why a workbook is not the Z-Report, or "" when it is."""
    if not x.has(SHEETS):
        return "missing sheet(s) " + ", ".join(s for s in SHEETS if not x.has([s]))
    if not {"code", "month", "name"} <= {norm(v) for v, _ in x.head("MAIN", 2).get(2, {}).values()}:
        return "MAIN row 2 has no Code, Month and Name"
    if not {"sales", "ff", "basket"} <= {norm(v) for v, _ in x.head("All Year", 3).get(3, {}).values()}:
        return "All Year row 3 has no SALES / FF / Basket blocks"
    return ""


def all_year(x):
    rows = x.head("All Year", 120)
    r2, r3 = rows.get(2, {}), rows.get(3, {})
    cols = {k: sorted(c for c, (v, _) in r3.items() if norm(v) == k) for k in ("sales", "ff")}
    horizon = sorted({m for m in (month_key(val(r2, c)) for c in cols["sales"]) if m})
    defs, at = [], {}
    for rn in sorted(rows):
        label = str(val(rows[rn], 2) or "").strip()
        if rn < 5 or not label:
            continue
        sf = next((formula(rows[rn], c) for c in cols["sales"] if formula(rows[rn], c)), "")
        ff = next((formula(rows[rn], c) for c in cols["ff"] if formula(rows[rn], c)), "")
        sc, fc = main_col(sf), main_col(ff)
        at[rn] = len(defs)
        defs.append({"row": rn, "label": label, "detail": bool(sc and fc), "sc": sc, "fc": fc, "deps": [] if sc and fc else dep_rows(sf)})
    n = 0
    for d in defs:
        d["di"] = n if d["detail"] else None
        n += d["detail"]
        d["deps"] = [at[r] for r in d["deps"] if r in at]
    grand = next((i for i, d in enumerate(defs) if norm(d["label"]) == "grand total"), len(defs) - 1)
    return horizon, defs, grand


def projected(x, defs):
    rows = x.head("AUTOMATED PROJECTED ZREPORT", 100)
    by_label = {norm(d["label"]): d["di"] for d in defs if d["detail"]}
    out, at = [], {}
    for rn in sorted(rows):
        label = str(val(rows[rn], 1) or "").strip()
        if rn < 5 or not label:
            continue
        di = by_label.get(norm(label))
        at[rn] = len(out)
        out.append({"label": label, "di": di, "deps": [] if di is not None else dep_rows(formula(rows[rn], 2))})
    for d in out:
        d["deps"] = [at[r] for r in d["deps"] if r in at]
    return out


def tidy(v):
    v = round(v, 2)
    return int(v) if float(v).is_integer() else v


def build(path, meta):
    x = Xlsx(path)
    try:
        why = check(x)
        if why:
            raise ValueError(why)
        horizon, defs, grand = all_year(x)
        prows = projected(x, defs)
        details = [d for d in defs if d["detail"]]
        if not details:
            raise ValueError("no All Year category maps to a MAIN column")
        cols = {}
        for c, (v, _) in x.head("MAIN", 2).get(2, {}).items():
            cols.setdefault(norm(v), c)
        names, months, network, summaries, actual = {}, {}, {}, {}, set()
        for rn, row in x.rows("MAIN"):
            if rn <= 2:
                continue
            code, raw = str(val(row, cols["code"]) or "").strip(), val(row, cols["month"])
            mk = month_key(raw)
            if not code or not mk:
                continue
            name = str(val(row, cols["name"]) or "").strip()
            s = [number(val(row, d["sc"])) for d in details]
            f = [number(val(row, d["fc"])) for d in details]
            if summary_row(code, raw):
                summaries[mk] = {"month": mk, "outlets": int(round(number(name))), "sales": [tidy(v) for v in s], "ff": [tidy(v) for v in f]}
                continue
            names[code] = name or names.get(code) or code
            actual.add(mk)
            om = months.setdefault(code, {})
            if mk in om:  # duplicate outlet-month rows are added up
                om[mk] = [[a + b for a, b in zip(om[mk][0], s)], [a + b for a, b in zip(om[mk][1], f)]]
            else:
                om[mk] = [s, f]
            nt = network.setdefault(mk, [0.0, 0.0])
            nt[0] += sum(s)
            nt[1] += sum(f)
        if not names:
            raise ValueError("no outlet rows in MAIN")
    finally:
        x.close()

    actual = sorted(actual)
    tmp = Path(tempfile.mkdtemp(prefix="zr-out-", dir=OUT.parent))
    outlets = []
    try:
        used = set()
        for code in sorted(names, key=lambda c: (c[:1], c)):
            base = re.sub(r"[^A-Za-z0-9_-]+", "_", code) or "OUTLET"
            fn, k = f"{base}.json", 2
            while fn in used:
                fn, k = f"{base}_{k}.json", k + 1
            used.add(fn)
            body = {"code": code, "name": names[code], "months": {m: [[tidy(v) for v in a], [tidy(v) for v in b]] for m, (a, b) in sorted(months[code].items())}}
            (tmp / fn).write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            outlets.append([code, names[code], f"{OUT_DIR.name}/{fn}", max(months[code])])  # last month with a row
        payload = {
            "schema": SCHEMA, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source": {"folder": FOLDER, **meta},
            "months": sorted(set(horizon) | set(actual)), "actual": actual,
            # [label, category index or null, [indexes of the rows it adds up]]
            "rows": [[d["label"], d["di"], d["deps"]] for d in defs], "grand": grand,
            "projRows": [[d["label"], d["di"], d["deps"]] for d in prows],
            "network": {m: [tidy(a), tidy(b)] for m, (a, b) in sorted(network.items())},
            "summaries": [summaries[m] for m in sorted(summaries)],
            "outlets": outlets,
        }
        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
        tmp.rename(OUT_DIR)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    t = OUT.with_suffix(".tmp")
    t.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(t, OUT)
    log(f"Wrote {OUT}: {len(outlets)} outlets, {len(details)} categories, {len(defs)} rows, months {actual[0]} to {actual[-1]}, {len(summaries)} all-outlet month rows.")


def score(name):
    n = name.lower()
    if n.startswith("~$") or not n.endswith((".xlsx", ".xlsm")):
        return 99
    if re.search(r"z[\s_-]*report.*category.*sales|category.*wise.*sales.*(ff|foot)|sales.*ff.*outlet", n):
        return 0
    if re.search(r"z[\s_-]*report|category.*wise.*sales|footfall.*outlet", n):
        return 1
    return 2  # still tried, after the named ones


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if "--local" in sys.argv:
        p = Path(sys.argv[sys.argv.index("--local") + 1])
        build(p, {"file": p.name, "key": "", "modified": ""})
        return 0
    import fetch_drive_data as drive
    log(f"Listing Drive folder {FOLDER}…")
    items = [i for i in drive.walk(FOLDER) if drive.is_spreadsheet(i)]
    for i in items:
        i["score"] = 0 if i["mimeType"] == drive.GSHEET_MIME and re.search(r"z[\s_-]*report", i["name"], re.I) else score(i["name"] if i["mimeType"] != drive.GSHEET_MIME else i["name"] + ".xlsx")
    items = sorted((i for i in items if i["score"] < 99), key=lambda i: (i["score"], -drive.modified_sort_key(i)))
    if not items:
        log("::warning::No workbook in the Z-Report folder; zr.json left as is.")
        return 1
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        old = prev.get("source", {}) if prev.get("schema") == SCHEMA else {}
    except (OSError, ValueError):
        old = {}
    with tempfile.TemporaryDirectory(prefix="zr-") as work:
        for item in items:
            key = f"{item['id']}|{item.get('modified', '')}"
            if old.get("key") == key and OUT_DIR.exists():
                log(f"Z-Report workbook unchanged ({item.get('path') or item['name']}); zr.json kept.")
                return 0
            path = Path(work) / "zr.xlsx"
            try:
                path.write_bytes(drive.fetch_bytes(item))
                build(path, {"file": item.get("path") or item["name"], "key": key, "modified": item.get("modified", "")})
                return 0
            except Exception as err:  # noqa: BLE001 - try the next candidate
                log(f"  skip  {item.get('path') or item['name']} ({err})")
    log("::error::No workbook in the Z-Report folder has the MAIN, All Year and AUTOMATED PROJECTED ZREPORT sheets; zr.json left as is.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
