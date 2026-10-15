#!/usr/bin/env python3
"""E-Commerce page: build data/ecom.json from the E-commerce Drive folder.

Sources, found in any sub-folder of the folder and recognised by their columns:
  * Sub-order exports, one workbook per delivery month. Some hold one row per sub-order (July to
    September), others one row per product (October). Each sub-order is counted once, in the month of its
    delivery slot. When two files hold the same sub-order, the file of the later month wins.
  * The complaints workbook (an "Order Id" and a complaint category column).

Regional leaders (RHO), zonals and outlet names come from the outlet master in data/data.json. Customer names,
phone numbers and e-mail addresses are never written to the output, and phone numbers or e-mails inside the
complaint text are masked. Product figures are only used for a month whose product lines add up to the
sub-order totals (October); the other months' product columns do not reconcile.

Output data/ecom.json (schema 1). Amounts are whole taka. Months are "YYYY-MM" by delivery slot.
  m          per month: n (sub-orders), orders, days, gmv (all), net (not cancelled), canc, custc (cancelled by
             the customer), boc (cancelled by back office), deliv (delivered, not cancelled), late, late60,
             lateMin, edited, cod, open (pending or processing)
  reasons    per month: cancellation reason -> sub-orders
  ered       per month: edit reason -> sub-orders
  slots      per month: [slot label, start hour, sub-orders, cancelled, delivered, late]
  zones      per month: zone -> sub-orders
  districts  per month: [district, sub-orders, net sales] (largest first)
  pays       per month: primary payment method -> sub-orders
  outlets    [code, name, RHO, zonal, district, month, sub-orders, net, cancelled, delivered, late, complaints]
  products   per month: [product, lines, sub-orders, amount] (only where the product lines reconcile)
  open       [order, sub-order, code, name, status, created, slot date, slot, payment, total, age in days]
  lists      dictionaries for the complaint rows: src, cat, sub, dbl, rl, zn
  complaints [month, src, order, code, name, rl, zn, cat, sub, dbl, details, feedback, order status,
             order total, slot date, matched to a sub-order (1/0)]

Environment:
  ECOM_FOLDER_ID  Drive folder to search (default: the E-commerce folder)
  ECOM_OUT        output file (default: data/ecom.json)
  DATA_OUT        the outlet master, data/data.json (default: data/data.json)
  DRIVE_CACHE     shared download cache (see scripts/network/fetch_drive_data.py)
Usage: python scripts/ecom/refresh.py
"""
import contextlib
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
sys.path.insert(0, str(HERE.parent / "network"))

FOLDER = (os.environ.get("ECOM_FOLDER_ID") or "1T73t5_KCNM7JdnuuklsbpzKvIwZ8cttn").strip()
OUT = Path(os.environ.get("ECOM_OUT") or ROOT / "data" / "ecom.json")
MASTER = Path(os.environ.get("DATA_OUT") or ROOT / "data" / "data.json")
SCHEMA = 1
MONTH_OF = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
SLOT_RE = re.compile(r"(\d{1,2}):(\d{2}) ([AP]M) - (\d{1,2}):(\d{2}) ([AP]M)\s+(\d{1,2})/(\d{1,2})/(\d{4})")
PHONE_RE = re.compile(r"(?:\+?88)?\s?0?1[3-9]\d(?:[-\s]?\d){7}|\b\d{7,}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
OPEN = ("Pending", "Processing")


def log(msg):
    print(msg, flush=True)


def txt(v):
    return re.sub(r"\s+", " ", str(v if v is not None else "").replace(" ", " ").replace("\xa0", " ")).strip()


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(txt(v).replace(",", "") or 0)
    except ValueError:
        return 0.0


def when(v):
    """'Oct 05, 2026, 7:57:33 AM' (text) or a date object -> naive datetime, else None."""
    if isinstance(v, dt.datetime):
        return v
    s = txt(v)
    if not s:
        return None
    try:
        return dt.datetime.strptime(s, "%b %d, %Y, %I:%M:%S %p")
    except ValueError:
        return None


def slot(v):
    """'09:00 PM - 10:00 PM 10/5/2026' -> (label, start hour, end hour, slot date), hours on a 24-hour clock."""
    m = SLOT_RE.search(txt(v))
    if not m:
        return None
    hour = lambda h, ap: int(h) % 12 + (12 if ap == "PM" else 0)  # noqa: E731
    label = f"{m[1]}:{m[2]} {m[3]} - {m[4]}:{m[5]} {m[6]}"
    return label, hour(m[1], m[3]), hour(m[4], m[6]), dt.date(int(m[9]), int(m[7]), int(m[8]))


def zone(v):
    s = txt(v)
    return "Red" if s in ("Red", "R") else (s or "Unassigned")


def pay(v):
    s = txt(v).split(",")[0].replace("Payments.", "").strip()
    return s or "(blank)"


def clean_text(v, limit=240):
    s = EMAIL_RE.sub("[email]", PHONE_RE.sub("[number]", txt(v)))
    return s[:limit]


def order_no(v):
    s = txt(v)
    return str(int(float(s))) if re.fullmatch(r"\d+(\.0+)?", s) else s


def iso(d):
    return d.isoformat() if d else ""


@contextlib.contextmanager
def first_sheet(path):
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        yield book.worksheets[0]
    finally:
        book.close()


def columns(head):
    """Header name -> column index (the first column of a repeated name)."""
    ix = {}
    for i, h in enumerate(head):
        ix.setdefault(h, i)
    return ix


def cell(r, i):
    return r[i] if i is not None and i < len(r) else None


def read_orders(ix, rows, stats):
    """Sub-orders of one export, keyed by (order, sub-order). Product lines are folded into their sub-order."""
    c = lambda name: ix.get(name)  # noqa: E731
    subs = {}
    prod = defaultdict(lambda: [0, 0.0, set()])
    price_ok = 0.0  # product line amounts of sub-orders not cancelled, for the reconciliation check
    for r in rows:
        o, s = order_no(cell(r, c("OrderNumber"))), txt(cell(r, c("SuborderNumber")))
        sl, cr = slot(cell(r, c("DeliveryTime"))), when(cell(r, c("CreatedOn")))
        if not o or not sl or not cr:
            continue
        label, sh, eh, day = sl
        end = dt.datetime.combine(day, dt.time(eh)) + (dt.timedelta(days=1) if eh <= sh else dt.timedelta(0))
        st = txt(cell(r, c("SubordeStatus")))
        key = (o, s)
        rec = subs.get(key)
        if rec is None:
            dark = txt(cell(r, c("DarkStore"))).split()
            code = txt(cell(r, c("Outlet Code"))) or (dark[-1] if dark else "")
            rec = subs[key] = {
                "o": o, "s": s, "m": f"{day:%Y-%m}", "day": day, "sh": sh, "end": end, "sl": label, "cr": cr,
                "code": code, "name": txt(cell(r, c("Outlet Name"))), "dist": txt(cell(r, c("DeliveryDistrict"))),
                "zone": zone(cell(r, c("Zone"))), "st": st, "ost": txt(cell(r, c("OrderStatus"))),
                "pay": pay(cell(r, c("PaymentMethod"))), "pst": txt(cell(r, c("PaymentStatus"))),
                "tot": num(cell(r, c("SubOrderTotal"))), "dl": when(cell(r, c("DeliveredOn"))),
                "why": txt(cell(r, c("CancellationReason"))), "src": txt(cell(r, c("CancellationSource"))),
                "edited": False, "ered": set(),
            }
        if txt(cell(r, c("Edit Status"))) == "Edited":
            rec["edited"] = True
        er = txt(cell(r, c("Edit Reason"))) if c("Edit Reason") is not None else ""
        if er:
            rec["ered"].add(er)
        if c("ProductName") is not None and st != "Cancelled":
            price = num(cell(r, c("Price")))
            price_ok += price
            name = txt(cell(r, c("ProductName")))
            if name:
                p = prod[name]
                p[0] += 1
                p[1] += price
                p[2].add(key)
    stats["prod_price"] = price_ok
    stats["prod_lines"] = sum(p[0] for p in prod.values())
    stats["prod_total"] = sum(rec["tot"] for rec in subs.values() if rec["st"] != "Cancelled")
    stats["prod"] = prod
    return subs


def read_complaints(ix, rows):
    rowsout = []
    c = lambda name: ix.get(name)  # noqa: E731
    cat_i = next((i for h, i in ix.items() if "categ" in h.lower() and "double" not in h.lower() and "sub" not in h.lower()), None)
    dbl_i = next((i for h, i in ix.items() if "categ" in h.lower() and "double" in h.lower()), None)
    sub_i = next((i for h, i in ix.items() if h.lower().startswith("sub categ")), None)
    for r in rows:
        oid = order_no(cell(r, c("Order Id")))
        cat = txt(cell(r, cat_i)) or "(not given)"
        if not oid and not txt(cell(r, c("Outlet Code"))):
            continue  # an empty line of the sheet
        rowsout.append({
            "month": txt(cell(r, c("Month"))), "src": txt(cell(r, c("Source"))), "order": oid,
            "code": txt(cell(r, c("Outlet Code"))), "name": txt(cell(r, c("Outlet Name"))), "cat": cat,
            "sub": txt(cell(r, sub_i)), "dbl": txt(cell(r, dbl_i)),
            "det": clean_text(cell(r, c("Complaint Details"))), "fb": clean_text(cell(r, c("Our feedback"))),
        })
    return rowsout


def read_master():
    try:
        data = json.loads(MASTER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {o["c"]: o for o in (data.get("master") or {}).get("outlets", []) if o.get("c")}


def main():
    import fetch_drive_data as drive

    log(f"Listing Drive folder {FOLDER}…")
    items = [i for i in drive.walk(FOLDER) if drive.is_spreadsheet(i)]
    if not items:
        log("No E-commerce workbooks in the Drive folder; ecom.json left as is.")
        return 0
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    fkey = "|".join(f"{i['id']}:{i.get('modified', '')}" for i in sorted(items, key=lambda i: i["id"]))
    if (old.get("source") or {}).get("key") == fkey and old.get("schema") == SCHEMA:
        log("E-commerce files unchanged; ecom.json kept.")
        return 0

    best = {}          # (order, sub-order) -> the record from the latest month's file
    prods = {}         # month -> product aggregates, only where the lines reconcile
    complaints = []
    used = []
    with tempfile.TemporaryDirectory(prefix="ecom-") as work:
        for item in items:
            local = Path(work) / "book.xlsx"
            try:
                local.write_bytes(drive.fetch_bytes(item))
            except Exception as err:  # noqa: BLE001
                log(f"::warning::{item['path']}: {err}")
                continue
            try:
                with first_sheet(local) as ws:
                    rows = ws.iter_rows(values_only=True)
                    head = [txt(h) for h in (next(rows, None) or [])]
                    ix = columns(head)
                    if {"OrderNumber", "SuborderNumber", "DeliveryTime", "SubordeStatus"} <= set(ix):
                        stats = {}
                        subs = read_orders(ix, rows, stats)
                        months = Counter(rec["m"] for rec in subs.values())
                        month = months.most_common(1)[0][0] if months else "?"
                        ratio = stats["prod_price"] / stats["prod_total"] if stats["prod_total"] else 0
                        if stats["prod_lines"] and 0.95 <= ratio <= 1.05:
                            prods[month] = stats["prod"]
                        elif stats["prod_lines"]:
                            log(f"  note  {item['path']}: product lines do not add up to the sub-order totals ({ratio:.2f}); products not used")
                        for key, rec in subs.items():
                            if key not in best or rec["m"] >= best[key]["m"]:
                                best[key] = rec
                        used.append({"path": item["path"], "kind": "orders", "rows": len(subs), "month": month})
                        log(f"  orders  {item['path']}: {len(subs)} sub-orders for {month}")
                    elif "Order Id" in ix and any("categ" in h.lower() for h in ix):
                        got = read_complaints(ix, rows)
                        complaints.extend(got)
                        used.append({"path": item["path"], "kind": "complaints", "rows": len(got)})
                        log(f"  complaints  {item['path']}: {len(got)} rows")
            except Exception as err:  # noqa: BLE001 - not a readable workbook
                log(f"  skip  {item['path']} ({err})")
    if not best:
        log("::warning::No sub-order workbook could be read; ecom.json left as is.")
        return 1

    recs = list(best.values())
    asof = max(rec["cr"] for rec in recs)
    months = sorted({rec["m"] for rec in recs})
    master = read_master()
    by_order = defaultdict(list)
    for rec in recs:
        by_order[rec["o"]].append(rec)

    def name_of(code, fallback=""):
        return (master.get(code) or {}).get("n") or fallback or code

    # per-month totals
    M = {m: {"n": 0, "orders": set(), "days": set(), "gmv": 0.0, "net": 0.0, "canc": 0, "custc": 0, "boc": 0,
             "deliv": 0, "late": 0, "late60": 0, "lateMin": 0.0, "edited": 0, "cod": 0, "open": 0} for m in months}
    reasons, ered, zones, pays = ({m: Counter() for m in months} for _ in range(4))
    slot_of, dist_of = ({m: {} for m in months} for _ in range(2))
    outl = {}
    for rec in recs:
        m = M[rec["m"]]
        m["n"] += 1
        m["orders"].add(rec["o"])
        m["days"].add(rec["day"])
        m["gmv"] += rec["tot"]
        cancelled = rec["st"] == "Cancelled"
        if cancelled:
            m["canc"] += 1
            m["custc"] += rec["src"] == "Customer"
            m["boc"] += rec["src"] == "BackOffice"
            reasons[rec["m"]][rec["why"] or "(not given)"] += 1
        else:
            m["net"] += rec["tot"]
        if rec["edited"]:
            m["edited"] += 1
        for e in rec["ered"]:
            ered[rec["m"]][e] += 1
        if rec["pay"].startswith("CashOnDelivery"):
            m["cod"] += 1
        if rec["st"] in OPEN:
            m["open"] += 1
        late = False
        if rec["dl"] and not cancelled:
            m["deliv"] += 1
            if rec["dl"] > rec["end"]:
                late = True
                mins = (rec["dl"] - rec["end"]).total_seconds() / 60
                m["late"] += 1
                m["late60"] += mins > 60
                m["lateMin"] += mins
        sl = slot_of[rec["m"]].setdefault(rec["sl"], [rec["sh"], 0, 0, 0, 0])
        sl[1] += 1
        sl[2] += cancelled
        sl[3] += bool(rec["dl"] and not cancelled)
        sl[4] += late
        zones[rec["m"]][rec["zone"]] += 1
        dn = rec["dist"] or "(blank)"
        d = dist_of[rec["m"]].setdefault(dn, [0, 0.0])
        d[0] += 1
        d[1] += 0 if cancelled else rec["tot"]
        pays[rec["m"]][rec["pay"]] += 1
        ok = outl.setdefault((rec["code"], rec["m"]), [0, 0.0, 0, 0, 0, rec["name"], rec["dist"]])
        ok[0] += 1
        ok[1] += 0 if cancelled else rec["tot"]
        ok[2] += cancelled
        ok[3] += bool(rec["dl"] and not cancelled)
        ok[4] += late
        if rec["name"] and not ok[5]:
            ok[5] = rec["name"]

    # complaints: order, outlet and month
    lists = {k: [] for k in ("src", "cat", "sub", "dbl", "rl", "zn")}
    where = {k: {} for k in lists}

    def enc(kind, value):
        value = value or ""
        if value not in where[kind]:
            where[kind][value] = len(lists[kind])
            lists[kind].append(value)
        return where[kind][value]

    year_of = lambda mon: asof.year - (1 if mon > asof.month else 0)  # noqa: E731
    complaint_rows, comp_count = [], Counter()
    matched = 0
    for c in complaints:
        mi = MONTH_OF.get(c["month"][:3].lower())
        if not mi:
            continue
        m = f"{year_of(mi)}-{mi:02d}"
        found = by_order.get(c["order"], [])
        if found:
            matched += 1
        code = c["code"] or (found[0]["code"] if found else "")
        mo = master.get(code) or {}
        day = found[0]["day"] if found else None
        status = found[0]["st"] if found else ""
        total = sum(r["tot"] for r in found)
        name = mo.get("n") or c["name"] or (found[0]["name"] if found else "")
        comp_count[(code, m)] += 1
        complaint_rows.append([m, enc("src", c["src"]), c["order"], code, name, enc("rl", mo.get("rl", "")),
                               enc("zn", mo.get("zn", "")), enc("cat", c["cat"]), enc("sub", c["sub"]),
                               enc("dbl", c["dbl"]), c["det"], c["fb"], status, round(total), iso(day), 1 if found else 0])

    # products: the top 100 for each month
    products = {}
    for m, prod in prods.items():
        top = sorted(prod.items(), key=lambda kv: kv[1][1], reverse=True)[:100]
        products[m] = [[name, p[0], len(p[2]), round(p[1])] for name, p in top]

    # open: pending or processing in the latest snapshot
    opened = []
    for rec in recs:
        if rec["st"] in OPEN:
            opened.append([rec["o"], rec["s"], rec["code"], master.get(rec["code"], {}).get("n") or rec["name"], rec["st"],
                           rec["cr"].strftime("%Y-%m-%d %H:%M"), iso(rec["day"]), rec["sl"], rec["pay"], round(rec["tot"]),
                           (asof.date() - rec["cr"].date()).days])
    opened.sort(key=lambda r: -r[-1])

    def rnd(x):
        return round(x) if isinstance(x, float) else x

    payload = {
        "schema": SCHEMA,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {"key": fkey, "asOf": asof.strftime("%Y-%m-%d %H:%M"), "files": used,
                   "complaintsMatched": matched, "complaints": len(complaint_rows)},
        "months": months,
        "days": {m: len(M[m]["days"]) for m in months},
        "m": {m: {"n": v["n"], "orders": len(v["orders"]), "days": len(v["days"]), "gmv": rnd(v["gmv"]),
                  "net": rnd(v["net"]), "canc": v["canc"], "custc": v["custc"], "boc": v["boc"], "deliv": v["deliv"],
                  "late": v["late"], "late60": v["late60"], "lateMin": rnd(v["lateMin"]), "edited": v["edited"],
                  "cod": v["cod"], "open": v["open"]} for m, v in M.items()},
        "reasons": {m: dict(reasons[m].most_common()) for m in months},
        "ered": {m: dict(ered[m].most_common()) for m in months},
        "slots": {m: sorted([[k, *v] for k, v in slot_of[m].items()], key=lambda r: r[1]) for m in months},
        "zones": {m: dict(zones[m]) for m in months},
        "districts": {m: sorted([[k, v[0], rnd(v[1])] for k, v in dist_of[m].items()], key=lambda r: -r[1])[:15] for m in months},
        "pays": {m: dict(pays[m]) for m in months},
        "outlets": sorted([[code, v[5] or name_of(code), (master.get(code) or {}).get("rl", ""),
                            (master.get(code) or {}).get("zn", ""), (master.get(code) or {}).get("dis", "") or v[6],
                            m, v[0], rnd(v[1]), v[2], v[3], v[4], comp_count[(code, m)]]
                           for (code, m), v in outl.items()], key=lambda r: (r[5], -r[7])),
        "products": products,
        "open": opened,
        "lists": lists,
        "complaints": complaint_rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT)
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(recs)} sub-orders, {len(complaint_rows)} complaints "
        f"({matched} matched to an order), {months[0]} to {months[-1]}, data to {asof:%d %b %Y %H:%M}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
