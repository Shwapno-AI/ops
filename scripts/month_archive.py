#!/usr/bin/env python3
"""Month-end archive for the Consumable and wastage, Availability and Outlet network data.

A new month's files replace the published data, so before and after each server refresh this keeps the finished
month in MONTH_ARCHIVE/<kind>-months/<YYYY-MM>/ (a Coolify persistent volume on the server) and writes an
index.json there; the pages offer the kept months in a "Data month" picker. The Store level report (SKU) keeps
its own months (scripts/sku/refresh.py, SKU_ARCHIVE).

  cw       data/cw.json         kept when its dates run from the 1st to the last day of one month
  network  data/network.json    kept when sales run through the last day of the report month (Outlet Network and
                                Growth & momentum)
  av       data/av.json         a stock snapshot: the latest snapshot of each month is kept (the month-end one once
                                the month is over); the month is the stock file's date

Environment:
  MONTH_ARCHIVE  archive root (unset: nothing is kept; the GitHub workflow leaves it unset)
  CW_OUT, NETWORK_OUT, AV_OUT  the published files (defaults: data/<file> in the repo)
Usage: python scripts/month_archive.py            # keep what the published files allow
       python scripts/month_archive.py --index    # only rewrite the index files
"""
import datetime as dt
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path(os.environ["MONTH_ARCHIVE"]) if os.environ.get("MONTH_ARCHIVE") else None
FILES = {
    "cw": Path(os.environ.get("CW_OUT") or ROOT / "data" / "cw.json"),
    "network": Path(os.environ.get("NETWORK_OUT") or ROOT / "data" / "network.json"),
    "av": Path(os.environ.get("AV_OUT") or ROOT / "data" / "av.json"),
}


def log(msg):
    print(msg, flush=True)


def last_day(month):
    y, m = int(month[:4]), int(month[5:7])
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - dt.timedelta(days=1)).isoformat()


def period_of(kind, doc):
    """(month, {"start", "end"}, whole month?) of a published file, or None when it carries no usable date."""
    if kind == "cw":
        r = doc.get("dateRange") or {}
        a, b = str(r.get("min") or ""), str(r.get("max") or "")
        if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", a) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", b)):
            return None
        m = b[:7]
        return m, {"start": a, "end": b}, a == f"{m}-01" and b == last_day(m)
    if kind == "network":
        s = doc.get("source") or {}
        m, b = str(s.get("reportMonth") or ""), str(s.get("salesThroughDate") or "")
        if not (re.fullmatch(r"\d{4}-\d{2}", m) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", b)):
            return None
        return m, {"start": f"{m}-01", "end": b}, b == last_day(m)
    if kind == "av":
        stock = next((f for f in doc.get("files") or [] if f.get("kind") == "stock"), None)
        if not stock:
            return None
        name = stock.get("name") or ""
        hit = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", name)  # "… 2.11.2026.csv" = day.month.year
        ts = re.search(r"(?<!\d)(1[6-9]\d{8}|2[01]\d{8})(?!\d)", name)  # "stock_extraction_report_1793075462" = when it was extracted
        try:
            if hit:
                day = dt.date(int(hit.group(3)), int(hit.group(2)), int(hit.group(1))).isoformat()
            elif ts:
                day = (dt.datetime.fromtimestamp(int(ts.group(1)), dt.timezone.utc) + dt.timedelta(hours=6)).date().isoformat()  # Dhaka
            else:
                day = str(stock.get("modified") or "")[:10]
            dt.date.fromisoformat(day)
        except ValueError:
            return None
        return day[:7], {"start": day, "end": day, "stockDate": day}, True  # a snapshot: the latest one of the month is kept
    return None


def index(kind):
    base = ARCHIVE / f"{kind}-months"
    if not base.is_dir():
        return
    months = []
    for d in sorted(base.iterdir()):
        f = d / FILES[kind].name
        if not (re.fullmatch(r"\d{4}-\d{2}", d.name) and f.is_file()):
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        p = period_of(kind, doc)
        months.append({"month": d.name, "period": p[1] if p else None, "generatedAt": doc.get("generatedAt")})
    tmp = base / "index.json.tmp"
    tmp.write_text(json.dumps({"months": months}, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, base / "index.json")


def keep(kind):
    src = FILES[kind]
    if not src.is_file():
        return
    try:
        doc = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    p = period_of(kind, doc)
    if not p or not p[2]:
        return
    month, per, _ = p
    dest = ARCHIVE / f"{kind}-months" / month
    try:
        kept = json.loads((dest / src.name).read_text(encoding="utf-8"))
        kp = period_of(kind, kept)
    except (OSError, ValueError):
        kept, kp = None, None
    if kept is not None:
        if (dest / src.name).read_bytes() == src.read_bytes():
            return  # already kept as it is
        if kind == "av" and kp and kp[1]["end"] > per["end"]:
            return  # a later snapshot of this month is already kept
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / (src.name + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dest / src.name)
    if kind == "network":  # the Drive file list behind it, for the data-quality notes
        sync = src.with_name("network-sync.json")
        if sync.is_file():
            shutil.copy2(sync, dest / sync.name)
    index(kind)
    log(f"Kept {kind} {month} ({per['start']} to {per['end']}) in {dest}.")


def main():
    if not ARCHIVE:
        return 0
    for kind in FILES:
        try:
            (ARCHIVE / f"{kind}-months").mkdir(parents=True, exist_ok=True)
            index(kind) if "--index" in sys.argv else keep(kind)
        except OSError as e:
            log(f"::warning::Month-end archive for {kind} not written: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
