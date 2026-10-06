#!/usr/bin/env python3
"""Refresh data/av.json for the Availability pages.

Reads the mother Google Drive folder (sub-folders included). Every file is
recognised by its STRUCTURE, never by its name or folder:

* SKU lists — a workbook whose sheets carry Article Code + Name + CAT3 and a
  flag column CORE / PROMO / KVI / ECOM marked "Y".
* DOS — Outlet Code + Article Code + Sales Qty + PER DAY (Sales Qty is 60 days).
* E-Commerce — Code + code + Monthly Average Sales (ECOM) + DOS 2 Days +
  Assortment for outlet.
* Stock — ProductCode + ProductName followed by one column per outlet code
  (CSV or Excel).
* KVI outlets — a single CODE column of outlet codes.
* Zone Distribution — CODE + Outlet Name + Format + Division + District +
  PNP Non PNP status + Status (the newest one in Drive wins).

Rules (agreed with operations):

* An outlet whose total Core+KVI+Promo stock is 0, or whose total Core+KVI+Promo
  DOS is 0, is left out everywhere, including E-Commerce.
* The browser decides availability from stock and per-day sales for the chosen
  days of cover. A pair with no DOS row (no sales in 60 days) stays in the
  count and is available when it has stock.
* E-Commerce counts only Assortment = YES pairs; available when stock >= DOS 2 Days.

Exit code 1 = the refresh failed; av.json is left untouched, so the dashboard
keeps showing the last good data.
"""
import csv
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "network"))
import fetch_drive_data as drive  # noqa: E402  (stdlib public-folder listing and download)
from openpyxl import load_workbook  # noqa: E402

FOLDER = (os.environ.get("AV_FOLDER_ID") or os.environ.get("DATA_FOLDER_ID") or "1Te9stxbcBsIIO8bNElPuDXXPovkk4v1l").strip()
OUT = Path(os.environ.get("AV_OUT") or ROOT / "data" / "av.json")
OUTLET_RE = re.compile(r"^[A-Z][0-9]{3,4}$")
FLAGS = ("core", "promo", "kvi", "ecom")
ZONE_HEADERS = {"code", "outlet name", "format", "division", "district", "pnp non pnp status", "status"}
DOS_HEADERS = {"outlet code", "article code", "sales qty", "per day"}
ECOM_HEADERS = {"code", "monthly average sales (ecom)", "dos 2 days", "assortment for outlet"}
MISS = "New/Closed outlets (Not Distributed)"


def log(msg):
    print(msg, flush=True)


def clean(v):
    return " ".join(str(v if v is not None else "").replace(" ", " ").split()).strip()


def norm(v):
    return clean(v).casefold()


def code_of(v):
    """Article codes arrive as numbers or text; 2400017.0 and '2400017' are the same SKU."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return clean(v)


def outlet_of(v):
    c = clean(v).upper()
    return c if OUTLET_RE.fullmatch(c) else ""


def num(v):
    if v in (None, ""):
        return 0.0
    try:
        f = float(str(v).replace(",", ""))
        return f if f == f else 0.0
    except ValueError:
        return 0.0


# ------------------------------------------------------------------ recognition
def workbook_heads(path, rows=6):
    """{sheet name: [normalised header cells of the first rows]} without loading whole sheets."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        return {ws.title: [[norm(c) for c in r] for r in ws.iter_rows(values_only=True, max_row=rows)] for ws in wb.worksheets}
    finally:
        wb.close()


def classify(path):
    head = path.read_bytes()[:8]
    if head[:4] != b"PK\x03\x04":
        # Text/CSV: only the stock matrix is expected in this form. Read the first line only.
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            first = next(csv.reader(f), [])
        cols = [norm(c) for c in first]
        if cols[:2] and {"productcode", "productname"} <= set(cols) and sum(bool(outlet_of(c)) for c in first) >= 10:
            return "stock"
        return None
    try:
        heads = workbook_heads(path)
    except Exception:  # noqa: BLE001 - unreadable workbook is simply not ours
        return None
    flag_sheets = 0
    for sheet, rows in heads.items():
        for r in rows:
            s = set(r)
            if {"article code", "name", "cat3"} <= s and s & set(FLAGS):
                flag_sheets += 1
                break
            if DOS_HEADERS <= s:
                return "dos"
            if ECOM_HEADERS <= s:
                return "ecom"
            if ZONE_HEADERS <= s:
                return "zones"
            if {"productcode", "productname"} <= s and sum(bool(outlet_of(c)) for c in r) >= 10:
                return "stock"
    if flag_sheets:
        return "lists"
    # KVI outlet list: one sheet, a CODE header and outlet codes below it.
    if len(heads) == 1:
        rows = next(iter(heads.values()))
        if rows and [c for c in rows[0] if c] == ["code"] and all(outlet_of(r[0]) for r in rows[1:] if r and r[0]):
            return "kviOutlets"
    return None


# ------------------------------------------------------------------ readers
def read_lists(path):
    """{sku: {name, division, newDivision, cat3, core, promo, kvi, ecom}} from the flag sheets."""
    wb = load_workbook(path, read_only=True, data_only=True)
    skus = {}
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            h = [norm(c) for c in next(rows, [])]
            flag = next((f for f in FLAGS if f in h), None)
            if not flag or "article code" not in h:
                continue
            ix = {k: h.index(k) for k in ("article code", "name", "division", "new division", "cat3", flag) if k in h}
            for r in rows:
                code = code_of(r[ix["article code"]]) if ix["article code"] < len(r) else ""
                if not code:
                    continue
                if norm(r[ix[flag]]) not in ("y", "yes", "1", "true"):
                    continue
                s = skus.setdefault(code, {"name": "", "division": "", "newDivision": "", "cat3": "", **{f: False for f in FLAGS}})
                s[flag] = True
                for key, col in (("name", "name"), ("division", "division"), ("newDivision", "new division"), ("cat3", "cat3")):
                    if not s[key] and col in ix and ix[col] < len(r):
                        s[key] = clean(r[ix[col]])
    finally:
        wb.close()
    return skus


def read_zones(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Final_Zone Dis"] if "Final_Zone Dis" in wb.sheetnames else wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        h = [clean(c) for c in next(rows)]
        ix = {k: i for i, k in enumerate(h)}
        g = lambda r, *names: next((clean(r[ix[n]]) for n in names if n in ix and ix[n] < len(r) and clean(r[ix[n]])), "")  # noqa: E731
        out = {}
        for r in rows:
            c = outlet_of(g(r, "CODE", "Outlet Code"))
            if not c or c in out:
                continue
            st = g(r, "Status")
            out[c] = {"n": g(r, "Outlet Name"), "rl": g(r, "Leader") or g(r, "Regional Head HR Name"), "rh": g(r, "Regional Head HR Name"),
                      "zn": g(r, "Zonal") or g(r, "Zonal HR Name"), "zh": g(r, "Zonal HR Name"), "div": g(r, "Division"), "dis": g(r, "District"),
                      "fmt": g(r, "Format"), "own": "Own" if st.upper().startswith("OWN") else "Franchise" if st.upper().startswith("FR") else st,
                      "pnp": g(r, "PNP Non PNP status"), "loc": g(r, "Location Type"), "area": g(r, "Area")}
        return out
    finally:
        wb.close()


def read_kvi_outlets(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        return {outlet_of(r[0]) for r in wb.worksheets[0].iter_rows(values_only=True) if r and outlet_of(r[0])}
    finally:
        wb.close()


def read_stock(path, wanted):
    """{outlet: {sku: stock}} for the wanted SKUs only; the file itself can be several hundred MB."""
    def rows_of():
        if path.read_bytes()[:4] == b"PK\x03\x04":
            wb = load_workbook(path, read_only=True, data_only=True)
            try:
                for ws in wb.worksheets:
                    it = ws.iter_rows(values_only=True)
                    first = next(it, [])
                    if {"productcode", "productname"} <= {norm(c) for c in first}:
                        yield list(first)
                        yield from it
                        return
            finally:
                wb.close()
        else:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
                yield from csv.reader(f)
    it = rows_of()
    h = next(it)
    hn = [norm(c) for c in h]
    si = hn.index("productcode")
    cols = [(j, outlet_of(c)) for j, c in enumerate(h) if outlet_of(c)]
    stock, outlets = {}, {o for _, o in cols}
    for r in it:
        code = code_of(r[si]) if si < len(r) else ""
        if code not in wanted:
            continue
        for j, o in cols:
            v = num(r[j]) if j < len(r) else 0.0
            if v:
                d = stock.setdefault(o, {})
                d[code] = d.get(code, 0.0) + v
    return stock, outlets


def read_dos(path, wanted):
    """{outlet: {sku: 60-day sales qty}} for the wanted SKUs."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            h = [norm(c) for c in next(it, [])]
            if not DOS_HEADERS <= set(h):
                continue
            io_, ia, iq = h.index("outlet code"), h.index("article code"), h.index("sales qty")
            out, rows = {}, 0
            for r in it:
                o, a = outlet_of(r[io_] if io_ < len(r) else None), code_of(r[ia] if ia < len(r) else None)
                if not o or a not in wanted:
                    continue
                rows += 1
                d = out.setdefault(o, {})
                d[a] = d.get(a, 0.0) + num(r[iq])
            return out, rows
    finally:
        wb.close()
    return {}, 0


def read_ecom(path):
    """[(outlet, sku, dos2days)] for Assortment = YES pairs, plus names and counts."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        for w in wb.worksheets:
            first = [norm(c) for c in next(w.iter_rows(values_only=True, max_row=1), [])]
            if ECOM_HEADERS <= set(first):
                ws = w
                break
        it = ws.iter_rows(values_only=True)
        raw = [clean(c) for c in next(it)]
        h = [c.casefold() for c in raw]
        io_ = raw.index("Code") if "Code" in raw else h.index("code")
        ia = raw.index("code") if "code" in raw and raw.index("code") != io_ else next(i for i, c in enumerate(h) if c == "code" and i != io_)
        idesc = h.index("description") if "description" in h else None
        iname = h.index("name") if "name" in h else None
        imon, idos, iasr = h.index("monthly average sales (ecom)"), h.index("dos 2 days"), h.index("assortment for outlet")
        pairs, names, total, no = [], {}, 0, 0
        for r in it:
            o, a = outlet_of(r[io_] if io_ < len(r) else None), code_of(r[ia] if ia < len(r) else None)
            if not o or not a:
                continue
            total += 1
            if iname is not None:
                names.setdefault(("o", o), clean(r[iname]))
            if idesc is not None:
                names.setdefault(("s", a), clean(r[idesc]))
            if norm(r[iasr]) != "yes":
                no += 1
                continue
            pairs.append((o, a, num(r[idos]), num(r[imon])))
        return pairs, names, total, no
    finally:
        wb.close()


# ------------------------------------------------------------------ build
def main():
    drive.MAX_DEPTH = 3
    with tempfile.TemporaryDirectory(prefix="av-") as work:
        work = Path(work)
        found = {k: [] for k in ("lists", "dos", "ecom", "stock", "zones", "kviOutlets")}
        log(f"Listing data folder {FOLDER}…")
        try:
            items = drive.walk(FOLDER)
        except RuntimeError as err:
            log(f"::error::{err}")
            return 1
        for n, item in enumerate(items):
            name = item["name"].lower()
            if not (name.endswith((".xlsx", ".xlsm", ".csv", ".txt")) or item["mimeType"] == drive.GSHEET_MIME):
                continue
            dest = work / f"{n}{Path(name).suffix or '.xlsx'}"
            try:
                dest.write_bytes(drive.fetch_bytes(item))
            except RuntimeError as err:
                log(f"::warning::{err}")
                continue
            kind = classify(dest)
            if not kind:
                dest.unlink()
                continue
            found[kind].append({"path": dest, "name": item["path"], "modified": drive.modified_sort_key(item)})
            log(f"  found {item['path']}  →  {kind}")
        need = [k for k in ("lists", "dos", "stock", "zones") if not found[k]]
        if need:
            log(f"::error::No {', '.join(need)} file recognised in the Drive folder.")
            return 1
        pick = {}
        for kind, options in found.items():
            if options:
                options.sort(key=lambda o: o["modified"], reverse=True)
                if len(options) > 1:
                    log(f"::warning::{len(options)} {kind} files found; using {options[0]['name']}. Others: {', '.join(o['name'] for o in options[1:])}")
                pick[kind] = options[0]

        lists = read_lists(pick["lists"]["path"])
        ckp = {c for c, s in lists.items() if s["core"] or s["promo"] or s["kvi"]}
        ecom_listed = {c for c, s in lists.items() if s["ecom"]}
        zones = read_zones(pick["zones"]["path"])
        kvi_outlets = read_kvi_outlets(pick["kviOutlets"]["path"]) if "kviOutlets" in pick else set()
        ecom_pairs, ecom_names, ecom_rows, ecom_no = read_ecom(pick["ecom"]["path"]) if "ecom" in pick else ([], {}, 0, 0)
        ecom_skus = ecom_listed | {a for _, a, _, _ in ecom_pairs}
        log(f"  lists: {len(ckp)} Core/Promo/KVI SKUs, {len(ecom_listed)} E-Commerce SKUs")
        stock, stock_outlets = read_stock(pick["stock"]["path"], ckp | ecom_skus)
        log(f"  stock: {len(stock_outlets)} outlet columns")
        dos, dos_rows = read_dos(pick["dos"]["path"], ckp)
        log(f"  DOS: {dos_rows} Core/Promo/KVI rows for {len(dos)} outlets")

    # Safeguard: a zone file that maps fewer than half the outlets (an old file, or one laid out differently) is
    # replaced by the outlet register the main build wrote to data.json, which keeps the last good register when
    # Drive has none, so the pages never lose their leaders and zonals.
    seen = stock_outlets | set(dos)
    mapped = sum(1 for o in seen if o in zones)
    if seen and mapped < 0.5 * len(seen):
        try:
            md = json.loads(Path(os.environ.get("DATA_OUT") or ROOT / "data" / "data.json").read_text(encoding="utf-8"))
            mo = (md.get("master") or {}).get("outlets") or []
        except (OSError, ValueError):
            mo = []
        if mo:
            log(f"::warning::{pick['zones']['name']} maps only {mapped} of {len(seen)} outlets; using the outlet register from data.json ({md['master'].get('file', '')}).")
            zones = {o["c"]: {**{k: o.get(k) or "" for k in ("n", "rh", "zh", "div", "dis", "fmt", "own", "pnp", "loc", "area")}, "rl": o.get("rl") or MISS, "zn": o.get("zn") or MISS} for o in mo if o.get("c")}
            pick["zones"] = {**pick["zones"], "name": f"{md['master'].get('file', 'data.json')} (outlet register; {pick['zones']['name']} could not be used)"}
        else:
            log(f"::warning::{pick['zones']['name']} maps only {mapped} of {len(seen)} outlets and no outlet register is available.")

    # Outlets: every outlet with stock or sales. An outlet with zero Core+KVI+Promo stock,
    # or zero Core+KVI+Promo DOS, is excluded everywhere.
    candidates = sorted(stock_outlets | set(dos))
    outlets, excluded = [], []
    for o in candidates:
        st = sum(v for a, v in stock.get(o, {}).items() if a in ckp)
        sl = sum(dos.get(o, {}).values())
        if st <= 0 or sl <= 0:
            reason = "No Core, KVI or Promo stock" if st <= 0 and sl > 0 else "No Core, KVI or Promo sales (DOS)" if sl <= 0 and st > 0 else "No Core, KVI or Promo stock or sales"
            excluded.append({"c": o, "n": zones.get(o, {}).get("n", ""), "reason": reason})
            continue
        z = zones.get(o) or {k: MISS for k in ("rl", "zn", "div", "dis", "fmt", "own", "pnp", "loc", "area")}
        outlets.append({"c": o, **{k: v for k, v in z.items()}, "n": z.get("n") if z.get("n") not in (None, MISS) else o,
                        "mapped": o in zones, "kvi": o in kvi_outlets, "ecom": False})
    oidx = {o["c"]: i for i, o in enumerate(outlets)}

    skus = sorted(ckp)
    sku_rows = [{"c": c, "n": lists[c]["name"], "div": lists[c]["division"], "nd": lists[c]["newDivision"], "cat3": lists[c]["cat3"],
                 "core": lists[c]["core"], "promo": lists[c]["promo"], "kvi": lists[c]["kvi"]} for c in skus]
    # Slot arrays, outlet-major: stock and 60-day sales (-1 = no DOS row, i.e. no sales in 60 days).
    rs = lambda v: round(v, 3) if v % 1 else int(v)  # noqa: E731
    st_arr, sl_arr = [], []
    for o in outlets:
        so, do = stock.get(o["c"], {}), dos.get(o["c"])
        for c in skus:
            st_arr.append(rs(so.get(c, 0.0)))
            sl_arr.append(rs(do[c]) if do is not None and c in do else -1)

    # E-Commerce: Assortment = YES pairs at outlets still counted.
    e_outlets = sorted({o for o, *_ in ecom_pairs if o in oidx})
    e_skus = sorted({a for o, a, *_ in ecom_pairs if o in oidx})
    e_set = set(e_outlets)
    for o in outlets:
        o["ecom"] = o["c"] in e_set
    e_si = {a: i for i, a in enumerate(e_skus)}
    e_pairs = [[oidx[o], e_si[a], rs(stock.get(o, {}).get(a, 0.0)), round(d2, 3), round(mon, 3)] for o, a, d2, mon in ecom_pairs if o in oidx]
    e_sku_rows = [{"c": a, "n": (lists.get(a) or {}).get("name") or ecom_names.get(("s", a), ""), "nd": (lists.get(a) or {}).get("newDivision", ""),
                   "cat3": (lists.get(a) or {}).get("cat3", "")} for a in e_skus]

    now = datetime.now(timezone.utc)
    files = [{"kind": k, "name": v["name"], "modified": datetime.fromtimestamp(v["modified"], timezone.utc).isoformat() if v["modified"] else None} for k, v in pick.items()]
    payload = {
        "schema": 1,
        "generatedAt": now.replace(microsecond=0).isoformat(),
        "files": files,
        "outlets": outlets, "excluded": excluded, "skus": sku_rows,
        "stock": st_arr, "sales60": sl_arr,
        "ecom": {"skus": e_sku_rows, "pairs": e_pairs, "listedRows": ecom_rows, "assortmentNo": ecom_no,
                 "excludedOutlets": sorted({o for o, *_ in ecom_pairs if o not in oidx})},
        "quality": {
            "zoneOutlets": len(zones), "stockOutlets": len(stock_outlets), "dosOutlets": len(dos),
            "unmappedOutlets": [o["c"] for o in outlets if not o["mapped"]],
            "kviOutletsListed": len(kvi_outlets), "kviOutletsCounted": sum(o["kvi"] for o in outlets),
            "skusNotInStock": sorted(c for c in ckp if not any(c in d for d in stock.values())),
            "skusNotInDos": sorted(c for c in ckp if not any(c in d for d in dos.values())),
            "ecomListedNotInFile": sorted(ecom_listed - {a for _, a, *_ in ecom_pairs}),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT)
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(outlets)} outlets counted, {len(excluded)} excluded, "
        f"{len(skus)} SKUs, {len(st_arr)} slots; E-Commerce {len(e_outlets)} outlets, {len(e_pairs)} YES pairs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
