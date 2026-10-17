#!/usr/bin/env python3
"""E-Commerce page: build data/ecom.json from the E-commerce Drive folder.

Sources, found in any sub-folder of the folder and recognised by their columns:
  * Sub-order exports, one workbook per delivery month. Some hold one row per sub-order (July to
    September), others one row per product (October). Each sub-order is counted once, in the month of its
    delivery slot. When two files hold the same sub-order, the file of the later month wins.
  * The complaints workbook (an "Order Id" and a complaint category column).

Regional leaders (RHO), zonals and outlet names come from the outlet master in data/data.json. Customer names
are included for the customer ranking; matching names can represent different people. Phone numbers and
e-mail addresses inside customer names or complaint text are masked. Contact columns are never exported.
Product figures are only used for a month whose product lines add up to the
sub-order totals (October); the other months' product columns do not reconcile.

Output data/ecom.json (schema 5; the fields below are schema 3). Every fact carries its outlet, so the page can narrow everything to a regional
leader, a zonal or one outlet. Aggregate amounts are whole taka; customer history keeps two decimal
places. Months are "YYYY-MM" and days "YYYY-MM-DD", both by delivery slot.
  months, mdays  the months and how many slot days each has
  days           the slot dates
  outlets        [[code, name, RHO, zonal], ...]; facts refer to outlets by their position here
  daily          columns by outlet and slot date: o, d, n (sub-orders), net (not cancelled), canc, custc
                 (cancelled by the customer), deliv (delivered, not cancelled), late (delivered after the slot
                 ended), late60, lateMin (minutes late, summed), edited, custed (edits the customer asked
                 for), open (pending or processing)
  why            {list: [reason], r: [[outlet, month, reason, who (0 customer, 1 back office, 2 not given), n]]}
  edits          {list: [reason], r: [[outlet, month, reason, sub-orders]]}
  slots          {list: [[label, start hour]], r: [[outlet, month, slot, weekday (0 = Monday), n, cancelled,
                 delivered, late]]}
  pays           {list: [method], r: [[outlet, month, method, n]]}
  dists          {list: [district], r: [[outlet, month, district, n, net]]}
  products       {month: [[product, lines, sub-orders, amount]]}, all outlets, top 100
  customers      {kind: "name", list: [display name], r: [[outlet, month, customer, parent order,
                 sub-orders, net amount]]}; customer -1 = missing name, -2 = conflicting names on the parent
                 order. Count distinct parent orders after filtering; counts include cancelled orders,
                 net amount excludes cancelled sub-orders. Names match by NFC, whitespace and casefold.
                 Additive historyVersion 1: asOf is the source reference date, statuses is a dictionary,
                 history is [[outlet, customer, parent order, sub-order, placed date, slot date, status,
                 gross amount, net amount]]. Dates are ISO days; status indexes statuses and reflects
                 the latest retained export, not the status at a past date. historyCoverage counts records
                 and omitted source rows with missing order numbers or dates. Omitted counts are source
                 rows, possibly repeated product lines, not distinct orders; missing-field reasons overlap.
  open           [[order, sub-order, outlet, status, placed, slot date, slot, payment, amount, days open]]
  lists          {src, cat, sub, dbl}: dictionaries for the complaint rows
  complaints     [[month, src, order, outlet, cat, sub, dbl, details, feedback, order status, order amount,
                 slot date, matched to a sub-order (1/0)]]

Added in schemas 4 and 5 (all additive, so the schema 3 fields above keep their meaning):
  source.files[].columns  every column of the workbook: {name, kind (num, text, date, empty), filled (non-empty
                 rows), distinct (capped at 61), use}. use is "used" (read by a field above), "dim" (charted in
                 dims), "num" (summed in nums), "private" (contact or identity details: never exported),
                 "id" (identifiers), "date", "text" (free text: listed only) or "empty".
  dims           {column: {list: [value], r: [[outlet, day, value, sub-orders, net]]}} by slot day: the payment
                 method, sub-order status and district, plus every other categorical column of the sub-order
                 exports with at most 60 values (for example Zone, OrderStatus, PaymentStatus).
  nums           {cols: [{name, level ("line": summed over product rows, "sub": once per sub-order)}],
                 r: [[outlet, day, value per column...]]}: every other numeric column, summed over sub-orders
                 that were not cancelled.
  placed         {r: [[outlet, month, weekday placed (0 = Monday), hour placed, sub-orders, delivered sub-orders]]},
                 by delivery month and CreatedOn time; delivered = status Complete.
  daily.slotch   sub-orders whose delivery slot was moved from the one the customer chose (see slotChange)
  daily.slotchLate  of those, delivered within the new slot but after the customer's slot had ended: late for the
                 customer, but not counted as late against the moved slot
  slotChange     {sources: [how changes were found], r: [[outlet, month, customer's slot, final slot, sub-orders,
                 delivered after the customer's slot]]}; slots index slots.list. Changes are found from any other
                 column holding a delivery slot (the customer's original slot), from a column flagging a reschedule,
                 and from a sub-order whose slot differs between two exports (the earlier export's slot counts as
                 the customer's). With none of these, sources is empty and nothing is counted.
  items          every product of the months whose exports have one row per product that adds up (see products):
                 {months: [month], list: [[product, SKU]], r: [[product, outlet, day, lines, sub-orders, quantity,
                 amount, discount, out-of-stock lines, quantity short, cancelled lines, cancelled amount]]}. Lines,
                 sub-orders, quantity, amount and discount are for sub-orders not cancelled; quantity short is the
                 ordered quantity less "Updated Qty" where it was cut; out-of-stock lines carry that edit reason.
  whyD, editsD   why and edits by slot day instead of month: {r: [[outlet, day, reason, who, n]]} and
                 {r: [[outlet, day, reason, sub-orders]]}; reasons index why.list and edits.list.

Environment:
  ECOM_FOLDER_ID  Drive folder to search (default: the E-commerce folder)
  ECOM_OUT        output file (default: data/ecom.json)
  DATA_OUT        the outlet master, data/data.json (default: data/data.json)
  DRIVE_CACHE     shared download cache (see scripts/network/fetch_drive_data.py)
Usage: python scripts/ecom/refresh.py [--local FOLDER]   (--local reads the workbooks in FOLDER instead of Drive)
"""
import contextlib
import datetime as dt
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "network"))

FOLDER = (os.environ.get("ECOM_FOLDER_ID") or "1T73t5_KCNM7JdnuuklsbpzKvIwZ8cttn").strip()
OUT = Path(os.environ.get("ECOM_OUT") or ROOT / "data" / "ecom.json")
MASTER = Path(os.environ.get("DATA_OUT") or ROOT / "data" / "data.json")
SCHEMA = 9  # 5: slot changes; 6: items (every product by outlet and day); 7: outlet codes from DarkStore; 9: placed = all and delivered. Bump to force a rebuild when fields are added
# columns read by the fields above; everything else in an export is classified for dims / nums
KNOWN = {"OrderNumber", "SuborderNumber", "DeliveryTime", "CreatedOn", "SubordeStatus", "DarkStore", "Outlet Code",
         "Outlet Name", "DeliveryDistrict", "PaymentMethod", "SubOrderTotal", "DeliveredOn", "CancellationReason",
         "CancellationSource", "Edit Status", "Edit Reason", "CustomerName", "ProductName", "Price"}
KNOWN_COMPLAINTS = {"Month", "Source", "Order Id", "Outlet Code", "Outlet Name", "Complaint Details", "Our feedback"}
# contact or identity details are never exported, whatever their values look like
PRIVATE_RE = re.compile(r"name|phone|mobile|contact|e-?mail|address|house|road|landmark|note|comment|remark|"
                        r"instruction|latitude|longitude|\blat\b|\blng\b|\bip\b|device|token|password|otp|\bnid\b|card", re.I)
ID_RE = re.compile(r"(^|[\s_])(id|no|number|code|sku|barcode|invoice|transaction|ref|reference)$|id$|number$", re.I)
MAX_DIM = 60
CUSTOMER_HISTORY_VERSION = 1
MONTH_OF = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
SLOT_RE = re.compile(r"(\d{1,2}):(\d{2}) ([AP]M) - (\d{1,2}):(\d{2}) ([AP]M)\s+(\d{1,2})/(\d{1,2})/(\d{4})")
PHONE_RE = re.compile(r"(?:\+?88)?\s?0?1[3-9]\d(?:[-\s]?\d){7}|\b\d{7,}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
OPEN = ("Pending", "Processing")
WHO = {"Customer": 0, "BackOffice": 1}
CUSTOMER_EDIT = "Customer Requested Change"
DAILY = ("n", "net", "canc", "custc", "deliv", "late", "late60", "lateMin", "edited", "custed", "open", "slotch", "slotchLate")
# a column that says the delivery slot was moved (a yes/no flag or a count), whatever else it is called
SLOTFLAG_RE = re.compile(r"reschedul|slot\s*_?chang|chang\w*\s*_?slot|time\s*_?chang|slot\s*_?updat|slot\s*_?moved", re.I)


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


def orig_end(sl):
    """End of a slot (label, start hour, end hour, day); a slot ending at or before its start ends the next day."""
    label, sh, eh, day = sl
    if eh is None:
        eh = slot(f"{label} {day.month}/{day.day}/{day.year}")[2]
    return dt.datetime.combine(day, dt.time(eh)) + (dt.timedelta(days=1) if eh <= sh else dt.timedelta(0))


def pay(v):
    s = txt(v).split(",")[0].replace("Payments.", "").strip()
    return s or "(not recorded)"


def clean_text(v, limit=400):
    s = EMAIL_RE.sub("[email]", PHONE_RE.sub("[number]", txt(v)))
    return s[:limit]


def customer_name(v):
    """A safe display name and its matching key; contact-only or generic values have no identity."""
    name = txt(clean_text(unicodedata.normalize("NFC", txt(v))))
    bare = txt(re.sub(r"\[(?:email|number)\]", " ", name, flags=re.I)).strip(" -–—_.,;:/\\()[]")
    if bare.casefold() in {"", "unknown", "guest", "anonymous", "none", "null", "n/a", "na",
                          "not recorded", "not given", "not available", "not applicable"}:
        return "", ""
    return name, unicodedata.normalize("NFC", name.casefold())


def order_no(v):
    s = txt(v)
    return str(int(float(s))) if re.fullmatch(r"\d+(\.0+)?", s) else s


def iso(d):
    return d.isoformat() if d else ""


class Codes:
    """A dictionary of repeated strings: value -> position in .list."""
    def __init__(self, values=()):
        self.list, self.at = [], {}
        for v in values:
            self(v)

    def __call__(self, value):
        value = value or ""
        if value not in self.at:
            self.at[value] = len(self.list)
            self.list.append(value)
        return self.at[value]


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


def is_number(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    return bool(re.fullmatch(r"-?[\d,]*\.?\d+", txt(v)))


def is_date(v):
    return isinstance(v, (dt.datetime, dt.date)) or bool(when(v)) or bool(SLOT_RE.search(txt(v)))


def profile(head, rows, known, sample=5000):
    """Kind, fill and distinct count of every column, from the first `sample` rows of the sheet."""
    out = []
    for i, h in enumerate(head):
        vals = [r[i] for r in rows[:sample] if i < len(r) and txt(r[i])]
        distinct = len({txt(v) for v in vals[:20000]} if vals else set())
        nums = sum(map(is_number, vals))
        kind = ("empty" if not vals else "num" if nums >= 0.9 * len(vals)
                else "date" if sum(map(is_date, vals[:200])) >= 0.9 * min(len(vals), 200) else "text")
        if h in known:
            use = "used"
        elif not vals:
            use = "empty"
        elif PRIVATE_RE.search(h):
            use = "private"
        elif ID_RE.search(h):
            use = "id"
        elif h != "DeliveryTime" and sum(1 for v in vals[:200] if SLOT_RE.search(txt(v))) >= 0.9 * min(len(vals), 200):
            use = "slot"   # another delivery slot: the one the customer chose before it was moved
        elif SLOTFLAG_RE.search(h):
            use = "slotflag"
        elif kind == "date":
            use = "date"
        elif kind == "num":
            use = "num"
        elif distinct <= MAX_DIM:
            use = "dim"
        else:
            use = "text"
        filled = sum(1 for r in rows if i < len(r) and txt(r[i]))
        out.append({"name": h or f"(column {i + 1})", "kind": kind, "filled": filled, "distinct": min(distinct, MAX_DIM + 1), "use": use, "i": i})
    return out


def read_orders(ix, rows, stats, extra=()):
    """Sub-orders of one export, keyed by (order, sub-order). Product lines are folded into their sub-order."""
    c = lambda name: ix.get(name)  # noqa: E731
    subs = {}
    prod = defaultdict(lambda: [0, 0.0, set()])
    stats.update({"omittedSourceRows": 0, "omittedMissingOrderRows": 0,
                  "omittedMissingPlacedDateRows": 0, "omittedMissingSlotDateRows": 0})
    price_ok = 0.0  # product line amounts of sub-orders not cancelled, for the reconciliation check
    for r in rows:
        o, s = order_no(cell(r, c("OrderNumber"))), txt(cell(r, c("SuborderNumber")))
        sl, cr = slot(cell(r, c("DeliveryTime"))), when(cell(r, c("CreatedOn")))
        if not o or not sl or not cr:
            stats["omittedSourceRows"] += 1
            stats["omittedMissingOrderRows"] += not bool(o)
            stats["omittedMissingPlacedDateRows"] += not bool(cr)
            stats["omittedMissingSlotDateRows"] += not bool(sl)
            continue
        label, sh, eh, day = sl
        end = dt.datetime.combine(day, dt.time(eh)) + (dt.timedelta(days=1) if eh <= sh else dt.timedelta(0))
        st = txt(cell(r, c("SubordeStatus")))
        key = (o, s)
        rec = subs.get(key)
        if rec is None:
            code = outlet_code(cell(r, c("DarkStore")), cell(r, c("Outlet Code")))
            rec = subs[key] = {
                "o": o, "s": s, "m": f"{day:%Y-%m}", "day": day, "sh": sh, "end": end, "sl": label, "cr": cr,
                "code": code, "name": txt(cell(r, c("Outlet Name"))), "dist": txt(cell(r, c("DeliveryDistrict"))),
                "st": st, "pay": pay(cell(r, c("PaymentMethod"))), "tot": num(cell(r, c("SubOrderTotal"))),
                "dl": when(cell(r, c("DeliveredOn"))), "why": txt(cell(r, c("CancellationReason"))),
                "src": txt(cell(r, c("CancellationSource"))), "edited": False, "ered": set(),
                "customers": {}, "xn": defaultdict(list), "xd": Counter(), "items": [],
            }
        name, name_key = customer_name(cell(r, c("CustomerName")))
        if name_key:
            rec["customers"].setdefault(name_key, name)
        for col in extra:
            v = cell(r, col["i"])
            if not txt(v):
                continue
            if col["use"] == "slot":
                rec["orig"] = rec.get("orig") or slot(v)
                rec["origCol"] = rec.get("origCol") or col["name"]
                continue
            if col["use"] == "slotflag":
                if txt(v).lower() not in ("0", "0.0", "no", "n", "false", "none", "not changed", "unchanged"):
                    rec["flag"] = col["name"]
                continue
            if col["use"] == "num":
                rec["xn"][col["name"]].append(num(v))
            else:
                rec["xd"][(col["name"], txt(v)[:80])] += 1
        if txt(cell(r, c("Edit Status"))) == "Edited":
            rec["edited"] = True
        er = txt(cell(r, c("Edit Reason"))) if c("Edit Reason") is not None else ""
        if er:
            rec["ered"].add(er)
        if c("ProductName") is not None and txt(cell(r, c("ProductName"))):
            upd = cell(r, c("Updated Qty"))
            rec["items"].append((txt(cell(r, c("ProductName"))), order_no(cell(r, c("SKU"))), num(cell(r, c("Quantity"))),
                                 num(cell(r, c("Price"))), num(cell(r, c("Discount"))), txt(cell(r, c("Edit Reason"))),
                                 num(upd) if txt(upd) else None))
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
            "code": outlet_code(cell(r, c("DarkStore")) if c("DarkStore") is not None else "", cell(r, c("Outlet Code"))), "name": txt(cell(r, c("Outlet Name"))), "cat": cat,
            "sub": txt(cell(r, sub_i)), "dbl": txt(cell(r, dbl_i)),
            "det": clean_text(cell(r, c("Complaint Details"))), "fb": clean_text(cell(r, c("Our feedback"))),
        })
    return rowsout


CODE_RE = re.compile(r"^[A-Z]\d{3}$")


def outlet_code(dark, code=""):
    """The outlet code is the last 4 characters of DarkStore ("Shwapno Green Road D007" -> D007); the Outlet Code
    column (which some exports fill with "Rang", "#N/A" or lower case) is used only when DarkStore has none."""
    d = re.sub(r"\s+", "", str(dark or "")).upper()[-4:]
    if CODE_RE.match(d):
        return d
    c = str(code or "").strip().upper()
    if CODE_RE.match(c):
        return c
    # no code anywhere: the outlet whose master name is in DarkStore (longest name wins), else "?"
    key = lambda t: re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()  # noqa: E731
    global _NAMES
    if _NAMES is None:
        _NAMES = sorted(((key(o.get("n")), oc) for oc, o in read_master().items() if key(o.get("n"))), key=lambda x: -len(x[0]))
    text = f" {key(dark)} "
    return next((oc for n, oc in _NAMES if f" {n} " in text), "?")


_NAMES = None


def read_master():
    try:
        data = json.loads(MASTER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {o["c"]: o for o in (data.get("master") or {}).get("outlets", []) if o.get("c")}


def list_items(local_dir):
    """The workbooks to read: Drive items, or the files of a local folder (--local)."""
    if local_dir:
        files = sorted(p for p in Path(local_dir).iterdir() if p.suffix.lower() in (".xlsx", ".xlsm") and not p.name.startswith("~$"))
        return [{"id": p.name, "name": p.name, "path": p.name, "local": str(p), "modified": str(int(p.stat().st_mtime))} for p in files], None
    import fetch_drive_data as drive
    log(f"Listing Drive folder {FOLDER}…")
    return [i for i in drive.walk(FOLDER) if drive.is_spreadsheet(i)], drive


def main():
    local_dir = sys.argv[sys.argv.index("--local") + 1] if "--local" in sys.argv else None
    items, drive = list_items(local_dir)
    if not items:
        log("No E-commerce workbooks in the Drive folder; ecom.json left as is.")
        return 0
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    fkey = "|".join(f"{i['id']}:{i.get('modified', '')}" for i in sorted(items, key=lambda i: i["id"]))
    if (not local_dir and (old.get("source") or {}).get("key") == fkey
            and old.get("schema") == SCHEMA
            and (old.get("customers") or {}).get("historyVersion") == CUSTOMER_HISTORY_VERSION):
        log("E-commerce files unchanged; ecom.json kept.")
        return 0

    best = {}          # (order, sub-order) -> the record from the latest month's file
    prods = {}         # month -> product aggregates, only where the lines reconcile
    complaints = []
    used = []
    history_coverage = {"omittedSourceRows": 0, "omittedMissingOrderRows": 0,
                        "omittedMissingPlacedDateRows": 0, "omittedMissingSlotDateRows": 0}
    with tempfile.TemporaryDirectory(prefix="ecom-") as work:
        for item in items:
            local = Path(item["local"]) if item.get("local") else Path(work) / "book.xlsx"
            if not item.get("local"):
                try:
                    local.write_bytes(drive.fetch_bytes(item))
                except Exception as err:  # noqa: BLE001
                    log(f"::warning::{item['path']}: {err}")
                    continue
            try:
                with first_sheet(local) as ws:
                    rows = ws.iter_rows(values_only=True)
                    head = [txt(h) for h in (next(rows, None) or [])]
                    rows = list(rows)
                    ix = columns(head)
                    if {"OrderNumber", "SuborderNumber", "DeliveryTime", "SubordeStatus"} <= set(ix):
                        stats = {}
                        cols = profile(head, rows, KNOWN)
                        first = set(ix.values())  # a repeated header name is read from its first column only
                        extra = [col for col in cols if col["use"] in ("num", "dim", "slot", "slotflag") and col["i"] in first]
                        subs = read_orders(ix, rows, stats, extra)
                        for field in history_coverage:
                            history_coverage[field] += stats[field]
                        months = Counter(rec["m"] for rec in subs.values())
                        month = months.most_common(1)[0][0] if months else "?"
                        ratio = stats["prod_price"] / stats["prod_total"] if stats["prod_total"] else 0
                        if stats["prod_lines"] and 0.95 <= ratio <= 1.05:
                            prods[month] = stats["prod"]
                        elif stats["prod_lines"]:
                            log(f"  note  {item['path']}: product lines do not add up to the sub-order totals ({ratio:.2f}); products not used")
                        for key, rec in subs.items():
                            old = best.get(key)
                            if old is None or rec["m"] >= old["m"]:
                                best[key] = rec
                            if old is not None and (old["sl"], old["day"]) != (rec["sl"], rec["day"]):
                                win, lose = (rec, old) if best[key] is rec else (old, rec)
                                if not win.get("orig"):
                                    win["orig"], win["origCol"] = (lose["sl"], lose["sh"], None, lose["day"]), "exports"
                        used.append({"path": item["path"], "kind": "orders", "rows": len(subs), "month": month,
                                     "sourceRows": len(rows), "columns": cols})
                        log(f"  orders  {item['path']}: {len(subs)} sub-orders for {month}")
                    elif "Order Id" in ix and any("categ" in h.lower() for h in ix):
                        got = read_complaints(ix, rows)
                        complaints.extend(got)
                        cat_cols = {h for h in ix if "categ" in h.lower()}
                        used.append({"path": item["path"], "kind": "complaints", "rows": len(got), "sourceRows": len(rows),
                                     "columns": profile(head, rows, KNOWN_COMPLAINTS | cat_cols)})
                        log(f"  complaints  {item['path']}: {len(got)} rows")
            except Exception as err:  # noqa: BLE001 - not a readable workbook
                log(f"  skip  {item['path']} ({err})")
    if not best:
        log("::warning::No sub-order workbook could be read; ecom.json left as is.")
        return 1

    recs = list(best.values())
    asof = max(rec["cr"] for rec in recs)
    months = sorted({rec["m"] for rec in recs})
    month_ix = {m: i for i, m in enumerate(months)}
    days = sorted({rec["day"] for rec in recs})
    day_ix = {d: i for i, d in enumerate(days)}
    master = read_master()
    by_order = defaultdict(list)
    for rec in recs:
        by_order[rec["o"]].append(rec)

    # Resolve identities after export/sub-order deduplication. A parent order can have several outlets,
    # sub-orders or product lines, but must belong to only one normalized name. Missing siblings inherit
    # that name; conflicting parents are retained as excluded coverage, never assigned to two customers.
    customer_names, customer_ix, customer_of = [], {}, {}
    for parent, parts in by_order.items():
        names = {}
        for rec in parts:
            for key, name in rec["customers"].items():
                names.setdefault(key, name)
        if len(names) != 1:
            customer_of[parent] = -2 if names else -1
            continue
        key, name = next(iter(names.items()))
        if key not in customer_ix:
            customer_ix[key] = len(customer_names)
            customer_names.append(name)
        customer_of[parent] = customer_ix[key]

    # outlets: name, RHO and zonal from the outlet master (zone distribution); a code the master does not know
    # keeps the export's name unless it is an error value
    outlets, outlet_ix = [], {}

    mo_known = lambda code: code in master  # noqa: E731

    def outlet(code, name=""):
        code = code or "?"
        if code not in outlet_ix:
            mo = master.get(code) or {}
            outlet_ix[code] = len(outlets)
            name = "" if re.match(r"^#(N/A|REF!|VALUE!|NAME\?)", name or "", re.I) else name
            outlets.append([code, mo.get("n") or name or code, mo.get("rl", ""), mo.get("zn", "")])
        elif name and not mo_known(code) and outlets[outlet_ix[code]][1] == code and not name.startswith("#"):
            outlets[outlet_ix[code]][1] = name
        return outlet_ix[code]

    slot_start = {}
    for rec in recs:
        slot_start.setdefault(rec["sl"], rec["sh"])
        if rec.get("orig"):
            slot_start.setdefault(rec["orig"][0], rec["orig"][1])
    slot_list = sorted(slot_start, key=lambda s: (slot_start[s], s))
    slot_ix = {s: i for i, s in enumerate(slot_list)}
    why_codes, edit_codes, pay_codes, dist_codes = Codes(), Codes(), Codes(), Codes()

    daily = defaultdict(lambda: [0] * len(DAILY))
    why, edits, pays = Counter(), Counter(), Counter()
    why_d, edits_d = Counter(), Counter()
    moves, sources = defaultdict(lambda: [0, 0]), set()
    slots = defaultdict(lambda: [0, 0, 0, 0])
    dists = defaultdict(lambda: [0, 0.0])
    customers = defaultdict(lambda: [0, 0.0])
    for rec in recs:
        o, m = outlet(rec["code"], rec["name"]), month_ix[rec["m"]]
        f = daily[(o, day_ix[rec["day"]])]
        cancelled = rec["st"] == "Cancelled"
        delivered = bool(rec["dl"]) and not cancelled
        late = delivered and rec["dl"] > rec["end"]
        f[0] += 1
        if cancelled:
            f[2] += 1
            f[3] += rec["src"] == "Customer"
            why[(o, m, why_codes(rec["why"] or "(not given)"), WHO.get(rec["src"], 2))] += 1
            why_d[(o, day_ix[rec["day"]], why_codes(rec["why"] or "(not given)"), WHO.get(rec["src"], 2))] += 1
        else:
            f[1] += rec["tot"]
        if delivered:
            f[4] += 1
        if late:
            mins = (rec["dl"] - rec["end"]).total_seconds() / 60
            f[5] += 1
            f[6] += mins > 60
            f[7] += mins
        f[8] += rec["edited"]
        f[9] += CUSTOMER_EDIT in rec["ered"]
        f[10] += rec["st"] in OPEN
        orig = rec.get("orig")
        moved = bool(orig) and (orig[0], orig[3]) != (rec["sl"], rec["day"])
        if moved or rec.get("flag"):
            sources.add(rec.get("origCol") if moved else rec["flag"])
            hidden = bool(moved and delivered and not late and rec["dl"] > orig_end(orig))
            f[11] += 1
            f[12] += hidden
            mv = moves[(o, m, slot_ix[orig[0]] if moved else -1, slot_ix[rec["sl"]])]
            mv[0] += 1
            mv[1] += hidden
        for e in rec["ered"]:
            edits[(o, m, edit_codes(e))] += 1
            edits_d[(o, day_ix[rec["day"]], edit_codes(e))] += 1
        s = slots[(o, m, slot_ix[rec["sl"]], rec["day"].weekday())]
        s[0] += 1
        s[1] += cancelled
        s[2] += delivered
        s[3] += late
        pays[(o, m, pay_codes(rec["pay"]))] += 1
        ds = dists[(o, m, dist_codes(rec["dist"] or "(not recorded)"))]
        ds[0] += 1
        ds[1] += 0 if cancelled else rec["tot"]
        cu = customers[(o, m, customer_of[rec["o"]], rec["o"])]
        cu[0] += 1
        cu[1] += 0 if cancelled else rec["tot"]

    # complaints: order, outlet and month
    lists = {k: Codes() for k in ("src", "cat", "sub", "dbl")}
    year_of = lambda mon: asof.year - (1 if mon > asof.month else 0)  # noqa: E731
    complaint_rows, matched = [], 0
    for c in complaints:
        mon = MONTH_OF.get(c["month"][:3].lower())
        if not mon:
            continue
        found = by_order.get(c["order"], [])
        matched += bool(found)
        o = outlet(c["code"] or (found[0]["code"] if found else ""), c["name"])
        complaint_rows.append([f"{year_of(mon)}-{mon:02d}", lists["src"](c["src"]), c["order"], o, lists["cat"](c["cat"]),
                               lists["sub"](c["sub"]), lists["dbl"](c["dbl"]), c["det"], c["fb"],
                               found[0]["st"] if found else "", round(sum(r["tot"] for r in found)),
                               iso(found[0]["day"]) if found else "", 1 if found else 0])

    products = {m: [[name, p[0], len(p[2]), round(p[1])] for name, p in sorted(prod.items(), key=lambda kv: -kv[1][1])[:100]]
                for m, prod in prods.items()}
    history_statuses = Codes(sorted({rec["st"] for rec in recs}))
    history = sorted(([outlet(rec["code"], rec["name"]), customer_of[rec["o"]], rec["o"], rec["s"],
                       iso(rec["cr"].date()), iso(rec["day"]), history_statuses(rec["st"]),
                       round(rec["tot"], 2), 0 if rec["st"] == "Cancelled" else round(rec["tot"], 2)]
                      for rec in recs), key=lambda r: (r[0], r[1], r[2], r[3]))
    history_coverage["records"] = len(history)
    # schema 6: every product of the months whose product lines add up, by outlet and slot day
    item_codes, item_at, item_rows = [], {}, defaultdict(lambda: [0, set(), 0.0, 0.0, 0.0, 0, 0.0, 0, 0.0])
    item_months = sorted(prods)
    for rec in recs:
        if rec["m"] not in prods or not rec["items"]:
            continue
        o, d_ix, cancelled = outlet(rec["code"], rec["name"]), day_ix[rec["day"]], rec["st"] == "Cancelled"
        for name, sku, qty, price, disc, reason, upd in rec["items"]:
            k = sku or name
            if k not in item_at:
                item_at[k] = len(item_codes)
                item_codes.append([name, sku])
            a = item_rows[(item_at[k], o, d_ix)]
            if cancelled:
                a[7] += 1
                a[8] += price
                continue
            a[0] += 1
            a[1].add((rec["o"], rec["s"]))
            a[2] += qty
            a[3] += price
            a[4] += disc
            a[5] += reason == "Out of Stock"
            if upd is not None and upd < qty:
                a[6] += qty - upd
    items = {"months": item_months, "list": item_codes,
             "r": [[*k, a[0], len(a[1]), round(a[2], 2), round(a[3]), round(a[4]), a[5], round(a[6], 2), a[7], round(a[8])]
                   for k, a in sorted(item_rows.items())]}

    # schema 4: categorical and numeric columns by outlet and slot day, and when orders were placed
    dim_vals = defaultdict(Codes)
    dim_rows = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    num_cols = {}
    for f in used:
        for col in f.get("columns", []):
            if f["kind"] == "orders" and col["use"] == "num":
                num_cols.setdefault(col["name"], "sub")
    num_rows = defaultdict(lambda: defaultdict(float))
    placed, placed_done = Counter(), Counter()
    for rec in recs:
        o, d_ix = outlet(rec["code"], rec["name"]), day_ix[rec["day"]]
        cancelled = rec["st"] == "Cancelled"
        net = 0 if cancelled else rec["tot"]
        values = {"Payment method": rec["pay"], "Sub-order status": rec["st"] or "(not recorded)",
                  "Delivery district": rec["dist"] or "(not recorded)"}
        best_of = {}
        for (name, value), n in rec["xd"].items():
            if n > best_of.get(name, ("", 0))[1]:
                best_of[name] = (value, n)
        values.update({name: v for name, (v, _) in best_of.items()})
        for name, value in values.items():
            a = dim_rows[name][(o, d_ix, dim_vals[name](value))]
            a[0] += 1
            a[1] += net
        if not cancelled:
            for name, vals in rec["xn"].items():
                if len(set(vals)) > 1:
                    num_cols[name] = "line"
        pk = (o, month_ix[rec["m"]], rec["cr"].weekday(), rec["cr"].hour)  # when orders were placed (CreatedOn)
        placed[pk] += 1
        if re.match(r"^(complete|completed|delivered)$", rec["st"].strip(), re.I):
            placed_done[pk] += 1
    for rec in recs:
        if rec["st"] == "Cancelled":
            continue
        o, d_ix = outlet(rec["code"], rec["name"]), day_ix[rec["day"]]
        for name, vals in rec["xn"].items():
            num_rows[(o, d_ix)][name] += sum(vals) if num_cols.get(name) == "line" else vals[0]
    for f in used:  # a column with too many values across all exports is free text after all
        for col in f.get("columns", []):
            if col["use"] == "dim" and len(dim_vals[col["name"]].list) > MAX_DIM:
                col["use"] = "text"
            col.pop("i", None)
    dims = {name: {"list": dim_vals[name].list, "r": [[*k, v[0], round(v[1])] for k, v in sorted(rows.items())]}
            for name, rows in dim_rows.items() if len(dim_vals[name].list) <= MAX_DIM or name == "Delivery district"}
    num_names = sorted(num_cols)
    nums = {"cols": [{"name": n, "level": num_cols[n]} for n in num_names],
            "r": [[*k, *[round(v.get(n, 0), 2) for n in num_names]] for k, v in sorted(num_rows.items())]}

    opened = sorted(([rec["o"], rec["s"], outlet(rec["code"], rec["name"]), rec["st"], rec["cr"].strftime("%Y-%m-%d %H:%M"),
                      iso(rec["day"]), rec["sl"], rec["pay"], round(rec["tot"]), (asof.date() - rec["cr"].date()).days]
                     for rec in recs if rec["st"] in OPEN), key=lambda r: -r[-1])

    keys = sorted(daily, key=lambda k: (k[1], k[0]))
    payload = {
        "schema": SCHEMA,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {"key": fkey, "asOf": asof.strftime("%Y-%m-%d %H:%M"), "files": used,
                   "complaintsMatched": matched, "complaints": len(complaint_rows)},
        "months": months,
        "mdays": {m: sum(1 for d in days if f"{d:%Y-%m}" == m) for m in months},
        "days": [iso(d) for d in days],
        "outlets": outlets,
        "daily": {"o": [k[0] for k in keys], "d": [k[1] for k in keys],
                  **{name: [round(daily[k][i]) for k in keys] for i, name in enumerate(DAILY)}},
        "why": {"list": why_codes.list, "r": [[*k, v] for k, v in sorted(why.items())]},
        "edits": {"list": edit_codes.list, "r": [[*k, v] for k, v in sorted(edits.items())]},
        "slots": {"list": [[s, slot_start[s]] for s in slot_list], "r": [[*k, *v] for k, v in sorted(slots.items())]},
        "pays": {"list": pay_codes.list, "r": [[*k, v] for k, v in sorted(pays.items())]},
        "dists": {"list": dist_codes.list, "r": [[*k, v[0], round(v[1])] for k, v in sorted(dists.items())]},
        "products": products,
        "items": items,
        "customers": {"kind": "name", "list": customer_names,
                      "r": [[*k, v[0], round(v[1])] for k, v in sorted(customers.items())],
                      "historyVersion": CUSTOMER_HISTORY_VERSION, "asOf": iso(asof.date()),
                      "statuses": history_statuses.list, "history": history,
                      "historyStatusBasis": "latest-export", "historyCoverage": history_coverage},
        "open": opened,
        "lists": {k: v.list for k, v in lists.items()},
        "complaints": complaint_rows,
        "dims": dims,
        "nums": nums,
        "placed": {"r": [[*k, v, placed_done[k]] for k, v in sorted(placed.items())]},
        "whyD": {"r": [[*k, v] for k, v in sorted(why_d.items())]},
        "slotChange": {"sources": sorted(sources), "r": [[*k, *v] for k, v in sorted(moves.items())]},
        "editsD": {"r": [[*k, v] for k, v in sorted(edits_d.items())]},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT)
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(recs)} sub-orders, {len(outlets)} outlets, "
        f"{len(complaint_rows)} complaints ({matched} matched to an order), {months[0]} to {months[-1]}, "
        f"data to {asof:%d %b %Y %H:%M}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
