#!/usr/bin/env python3
"""Item performance pages: build data/sku.json.

Source: the "Item Dashboard performance workbooks" Drive folder, one workbook per regional
leader with one row per outlet x SKU and this-year / last-year POS sales (NSI), GP value
(GPV) and sales quantity. Files are recognised by their columns, never by name, and the
column names may vary (e.g. "POS NSI This" or "Sales This").

The workbooks are large (hundreds of MB), so the build streams them once and publishes
compact summaries: outlet totals, outlet x division x Cat 01, SKU totals (all stores and
same store), SKU x regional leader, and each outlet's biggest gaining and declining SKUs.
It skips the rebuild when no workbook changed since the last build.

Footfall and basket size are left out: in these files they are per SKU line, so they
cannot be added across SKUs.

Environment:
  SKU_FOLDER_ID  Drive folder (default: Item Dashboard performance workbooks)
  SKU_OUT        output file (default: data/sku.json)
  DATA_OUT       data.json with the outlet master and the same-store list (default: data/data.json)
  DRIVE_CACHE    shared download cache (see scripts/network/fetch_drive_data.py)
Usage: python scripts/sku/refresh.py [--local DIR]   # DIR of .xlsx / .csv files instead of Drive

The workbooks may also come as CSV exports with the same columns (one file per regional leader).
"""
import csv
import datetime as dt
import hashlib
import heapq
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "network"))
import xlsx_stream  # noqa: E402

FOLDER = (os.environ.get("SKU_FOLDER_ID") or "111qtlTIgOpvuYK7G4B_xrA8hRBpwjcj_").strip()
OUT = Path(os.environ.get("SKU_OUT") or ROOT / "data" / "sku.json")
MASTER = Path(os.environ.get("DATA_OUT") or ROOT / "data" / "data.json")
OUT_RL = OUT.with_name("sku-rl.json")
CW = Path(os.environ.get("CW_OUT") or ROOT / "data" / "cw.json")  # SKU x regional leader, loaded only when the SKUs page is set to one leader
TOP = 15  # gaining / declining SKUs kept per outlet
MISS = "New/Closed outlets (Not Distributed)"  # outlets not in the Zone Distribution
OUTLET_DIR = OUT.parent / "sku-outlet"  # one file per outlet with its full SKU list (built on the server, not committed)
OUTLET_FILES = os.environ.get("SKU_OUTLET_FILES", "1") != "0"  # the GitHub workflow turns them off (they are never committed)


def outlet_file(code):
    return re.sub(r"[^A-Za-z0-9_-]", "_", code) + ".json"


class OutletWriter:
    """Streams each outlet's SKU rows to its own file. A workbook's rows of one outlet usually
    arrive together, so only the current outlet is held in memory; a later run is appended."""

    def __init__(self, folder):
        self.dir, self.code, self.rows, self.done = Path(folder), None, [], set()
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)

    def add(self, code, row):
        if code != self.code:
            self.flush()
            self.code = code
        self.rows.append(row)

    def flush(self):
        if self.code and self.rows:
            f = self.dir / outlet_file(self.code)
            rows = self.rows
            if self.code in self.done:
                rows = json.loads(f.read_text(encoding="utf-8"))["rows"] + rows
            f.write_text(json.dumps({"c": self.code, "rows": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            self.done.add(self.code)
        self.rows = []


def log(msg):
    print(msg, flush=True)


def key(v):
    return re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()


# column -> accepted header names (normalised)
COLS = {
    "code": ["outlet code", "outlet", "site code"], "oname": ["outlet name"],
    "rl": ["regional head hr name", "regional head name", "regional head", "rho", "leader"],
    "zn": ["zonal name", "zonal hr name", "zonal", "zone name"],
    "sku": ["sku", "article", "article code", "article no"], "sname": ["sku name", "article name"],
    "div": ["division"], "c1": ["cat 01", "cat01", "category 01"], "c3": ["cat 03", "cat03", "category 03"],
    "ns": ["pos nsi this", "sales this", "nsi this", "pos sales this"], "nl": ["pos nsi last", "sales last", "nsi last", "pos sales last"],
    "gs": ["pos gpv this", "gpv this", "gp value this"], "gl": ["pos gpv last", "gpv last", "gp value last"],
    "qs": ["pos sales qty this", "sales qty this", "sales quantity this"], "ql": ["pos sales qty last", "sales qty last", "sales quantity last"],
}
REQUIRED = ("code", "sku", "ns", "nl")
VALS = ("ns", "nl", "gs", "gl", "qs", "ql")


def header_map(row):
    h = [key(x) for x in row]
    m = {}
    for name, alts in COLS.items():
        for a in alts:
            if a in h:
                m[name] = h.index(a)
                break
    return m if all(k in m for k in REQUIRED) else None


def modified_iso(text):
    """Drive's public listing gives '5:43 pm' for today or 'Sep 27' / 'Sep 27, 2025' for older files."""
    import fetch_drive_data as drive
    ts = drive.modified_sort_key({"modified": text})
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() if ts else ""


def num(v):
    if isinstance(v, float):
        return v
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def data_period(total, modified_dates):
    """The workbooks carry no dates. Find the day whose running total of daily POS NSI (from the
    till-date sales file behind cw.json) equals the workbooks' total sales; fall back to the day
    before the workbooks were last changed."""
    try:
        cw = json.loads(CW.read_text(encoding="utf-8"))
        by = defaultdict(float)
        for r in cw.get("daily") or []:
            if r.get("sales"):
                by[r["date"]] += r["sales"]
        days = sorted(d for d in by if by[d])
        if days and total > 0:
            month = days[-1][:7]
            cum, best = 0.0, None
            for d in (x for x in days if x.startswith(month)):
                cum += by[d]
                err = abs(cum / total - 1)
                if best is None or err < best[1]:
                    best = (d, err)
            if best and best[1] <= 0.01:
                return {"start": month + "-01", "end": best[0], "method": "matched to daily sales"}
    except (OSError, ValueError, KeyError):
        pass
    mods = [m for m in modified_dates if re.match(r"\d{4}-\d{2}-\d{2}", m or "")]
    if mods:
        end = (dt.date.fromisoformat(max(mods)[:10]) - dt.timedelta(days=1)).isoformat()
        return {"start": end[:8] + "01", "end": end, "method": "estimated from file date"}
    return None


def is_csv(name):
    return str(name).lower().endswith(".csv")


def table_rows(path):
    """Rows of the first sheet of an .xlsx workbook, or of a .csv export with the same columns."""
    if is_csv(path):
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            yield from csv.reader(fh)
    else:
        yield from xlsx_stream.rows(path)


def sources(workdir):
    """Download (or list) the workbooks and CSV exports; returns [(path, name, modified, drive_id)]."""
    import fetch_drive_data as drive
    items = [i for i in drive.walk(FOLDER) if drive.is_spreadsheet(i) or is_csv(i["name"])]
    out = []
    for n, item in enumerate(items):
        dest = Path(workdir) / f"{n}{'.csv' if is_csv(item['name']) else '.xlsx'}"
        try:
            dest.write_bytes(drive.fetch_bytes(item))
        except Exception as err:  # noqa: BLE001
            log(f"::warning::{item['path']}: {err}")
            continue
        out.append((dest, item["path"], item.get("modified", ""), item["id"]))
    return out


def main():
    local = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None
    try:
        md = json.loads(MASTER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        md = {}
    master = {o["c"]: o for o in ((md.get("master") or {}).get("outlets") or [])}
    same = {o["c"] for o in ((md.get("tilldate") or {}).get("outlets") or []) if o.get("ssy")}

    with tempfile.TemporaryDirectory(prefix="sku-") as work:
        if local:
            files = [(p, p.name, str(p.stat().st_mtime), p.name) for p in sorted(Path(local).iterdir()) if p.suffix.lower() in (".xlsx", ".csv")]
        else:
            log(f"Listing Drive folder {FOLDER}…")
            files = sources(work)
        # Keep only item-performance workbooks (checked on the header row).
        picked = []
        for path, name, mod, fid in files:
            try:
                first = next(table_rows(path), None)
            except Exception:  # noqa: BLE001 - not a readable workbook
                first = None
            hm = header_map(first or [])
            if hm:
                picked.append((path, name, mod, fid, hm))
            else:
                log(f"  skip  {name}  (not an item-performance layout)")
        if not picked:
            log("::error::No item-performance workbooks found; sku.json left as is.")
            return 1

        fingerprint = hashlib.sha256(json.dumps(sorted((f[3], f[2]) for f in picked)).encode()).hexdigest()[:20]
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
            if old.get("fingerprint") == fingerprint and old.get("schema") == 2 and OUT_RL.exists() and (OUTLET_DIR.is_dir() or not OUTLET_FILES):
                per = data_period(sum(o["t"][0] for o in old.get("outlets") or []), [f.get("modifiedIso", "") for f in old.get("source", {}).get("files", [])])
                if per and per != old.get("period"):
                    old["period"] = per
                    tmp = OUT.with_suffix(".tmp")
                    tmp.write_text(json.dumps(old, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                    os.replace(tmp, OUT)
                    log(f"Workbooks unchanged; data period updated to {per['start']} to {per['end']} ({per['method']}).")
                else:
                    log("No workbook changed since the last build; sku.json left as is.")
                return 0
        except (OSError, ValueError):
            pass

        outlets = {}
        cube = defaultdict(lambda: [0.0] * 6)            # (outlet, division, cat01) -> sums
        sku = {}                                         # sku -> catalog + sums
        sku_same = defaultdict(lambda: [0.0] * 6)
        sku_rl = defaultdict(lambda: [0.0] * 6)          # (sku, rl) -> sums
        gain, drop = defaultdict(list), defaultdict(list)  # outlet -> bounded heaps of (diff, sku, vals)
        rows_read = bad = 0
        files_meta = []
        ow = OutletWriter(OUT.parent / "sku-outlet.tmp")  # [sku, sales this, sales last, gp this, gp last, qty this, qty last]
        for path, name, mod, fid, hm in picked:
            n_file = 0
            it = table_rows(path)
            next(it, None)
            for r in it:
                g = lambda k: r[hm[k]] if k in hm and hm[k] < len(r) else None  # noqa: E731
                code = str(g("code") or "").strip().upper()
                s = str(g("sku") or "").strip()
                if s.endswith(".0"):
                    s = s[:-2]
                if not code or not s:
                    bad += 1
                    continue
                v = [num(g(k)) for k in VALS]
                n_file += 1
                m = master.get(code, {})
                # an outlet missing from the Zone Distribution counts as New/Closed (Not Distributed); the leader named
                # in the file is used only when no outlet register could be read at all
                rl = (m.get("rl") or MISS) if master else (str(g("rl") or "").strip() or MISS)
                o = outlets.get(code)
                if o is None:
                    oname = str(g("oname") or code)
                    o = outlets[code] = {"c": code, "n": m.get("n") or re.sub(r"^" + re.escape(code) + r"\s*-\s*", "", oname),
                                         "rlf": str(g("rl") or "").strip(), "znf": str(g("zn") or "").strip(), "t": [0.0] * 6}
                t = o["t"]
                for i in range(6):
                    t[i] += v[i]
                div, c1 = str(g("div") or "Not set").strip(), str(g("c1") or "Not set").strip()
                cb = cube[(code, div, c1)]
                for i in range(6):
                    cb[i] += v[i]
                k = sku.get(s)
                if k is None:
                    k = sku[s] = {"name": str(g("sname") or s).strip(), "div": div, "c1": c1, "c3": str(g("c3") or "").strip(), "t": [0.0] * 6}
                for i in range(6):
                    k["t"][i] += v[i]
                if code in same:
                    ss = sku_same[s]
                    for i in range(6):
                        ss[i] += v[i]
                sr = sku_rl[(s, rl)]
                for i in range(6):
                    sr[i] += v[i]
                if OUTLET_FILES and any(v):
                    ow.add(code, [s, *[round(x) for x in v]])
                d = v[0] - v[1]
                if d > 0:
                    h = gain[code]
                    (heapq.heappush if len(h) < TOP else heapq.heappushpop)(h, (d, s, v[:4]))
                elif d < 0:
                    h = drop[code]
                    (heapq.heappush if len(h) < TOP else heapq.heappushpop)(h, (-d, s, v[:4]))
            rows_read += n_file
            files_meta.append({"name": name, "rows": n_file, "modified": mod, "modifiedIso": modified_iso(mod)})
            log(f"  read  {name}: {n_file} rows")
        ow.flush()

    sku_ids = sorted(sku)
    sidx = {s: i for i, s in enumerate(sku_ids)}
    rls = sorted({k[1] for k in sku_rl})
    ridx = {r: i for i, r in enumerate(rls)}
    rnd = lambda x: [round(y) for y in x]  # noqa: E731  (whole taka and units)
    divs = sorted({k["div"] for k in sku.values()} | {k[1] for k in cube})
    c1s = sorted({k["c1"] for k in sku.values()} | {k[2] for k in cube})
    c3s = sorted({k["c3"] for k in sku.values()})
    di, c1i, c3i = ({v: i for i, v in enumerate(a)} for a in (divs, c1s, c3s))
    top = []
    for heaps in (gain, drop):
        for code, h in heaps.items():
            for _, s, v in sorted(h, reverse=True):
                top.append([code, sidx[s], *rnd(v)])
    outs = []
    for code, o in outlets.items():
        m = master.get(code, {})
        if master and code not in master:
            rl_, zn_ = MISS, MISS  # not in the Zone Distribution
        else:
            rl_, zn_ = m.get("rl") or o["rlf"] or None, m.get("zn") or o["znf"] or None
        outs.append({"c": code, "n": o["n"], "ss": code in same, "t": rnd(o["t"]), "rl": rl_, "zn": zn_,
                     **{k: m.get(k) for k in ("div", "dis", "fmt", "own", "pnp", "loc")}})
    total = sum(o["t"][0] for o in outs)
    period = data_period(total, [f["modifiedIso"] for f in files_meta])
    if period:
        log(f"Data period {period['start']} to {period['end']} ({period['method']}).")
    payload = {
        "schema": 2, "fingerprint": fingerprint, "period": period,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {"folder": FOLDER, "files": files_meta, "rows": rows_read, "badRows": bad,
                   "fields": ["sales this", "sales last", "GP this", "GP last", "qty this", "qty last"]},
        "sameStoreCount": len(same),
        "outlets": outs,
        "divs": divs, "c1s": c1s, "c3s": c3s,
        # [outlet, division idx, cat01 idx, sales this, sales last, gp this, gp last, qty this, qty last]
        "cube": [[c, di[d], c1i[c1], *rnd(v)] for (c, d, c1), v in cube.items()],
        # [code, name, division idx, cat01 idx, cat03 idx, 6 sums (all stores), 6 sums (same store)]
        "skus": [[s, sku[s]["name"], di[sku[s]["div"]], c1i[sku[s]["c1"]], c3i[sku[s]["c3"]], *rnd(sku[s]["t"]), *rnd(sku_same.get(s, [0.0] * 6))] for s in sku_ids],
        "rls": rls,
        # [outlet, sku index, sales this, sales last, gp this, gp last]; biggest gainers and decliners per outlet
        "outletTop": top,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTLET_FILES:
        shutil.rmtree(OUTLET_DIR, ignore_errors=True)
        os.replace(OUT.parent / "sku-outlet.tmp", OUTLET_DIR)
    else:
        shutil.rmtree(OUT.parent / "sku-outlet.tmp", ignore_errors=True)
    # [sku index, rl index, 6 sums]
    rl_payload = {"fingerprint": fingerprint, "skuRl": [[sidx[s], ridx[r], *rnd(v)] for (s, r), v in sku_rl.items()]}
    tmp_rl = OUT_RL.with_suffix(".tmp")
    tmp_rl.write_text(json.dumps(rl_payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp_rl, OUT_RL)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT)
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(files_meta)} workbooks, {rows_read} rows, {len(outs)} outlets, {len(sku_ids)} SKUs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
