#!/usr/bin/env python3
"""Receiving pages: build data/rcv.json.

The receiving figures come from the public Power BI report behind the Receiving
dashboard. That dashboard's own workflow reads the report every few minutes and
publishes a snapshot (snapshot.json); this script downloads that snapshot, keeps
what the pages use, and joins each outlet to the outlet master in data.json
(regional leader, zonal, division and so on) so the sidebar filters work.

Standard library only. A failed run keeps the last good rcv.json.

Environment:
  RCV_SNAPSHOT_URL  snapshot to read (default: the Receiving dashboard's snapshot.json)
  RCV_OUT           output file (default: data/rcv.json)
  DATA_OUT          data.json holding the outlet master (default: data/data.json)
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_URL = os.environ.get("RCV_SNAPSHOT_URL") or "https://aftabz-lab.github.io/receiving-dashboard-shwapno/snapshot.json"
OUT = Path(os.environ.get("RCV_OUT") or ROOT / "data" / "rcv.json")
MASTER = Path(os.environ.get("DATA_OUT") or ROOT / "data" / "data.json")
DIMS = ("rl", "zn", "div", "dis", "fmt", "own", "pnp", "loc")


def log(msg):
    print(msg, flush=True)


def fetch(url, attempts=4):
    last = None
    for n in range(1, attempts + 1):
        try:
            req = urllib.request.Request(f"{url}{'&' if '?' in url else '?'}t={int(time.time())}", headers={"User-Agent": "ops-dashboard receiving sync", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            last = err
            time.sleep(3 * n)
    raise RuntimeError(f"Could not download the receiving snapshot: {last}")


def num(v, nd=2):
    return round(v, nd) if isinstance(v, (int, float)) else None


def main():
    log(f"Downloading {SNAPSHOT_URL}")
    snap = fetch(SNAPSHOT_URL)
    if not snap.get("ready") or not snap.get("outlets") or not snap.get("kpis"):
        log("::error::The receiving snapshot is incomplete; rcv.json left as is.")
        return 1

    master = {}
    try:
        for o in (json.loads(MASTER.read_text(encoding="utf-8")).get("master") or {}).get("outlets") or []:
            master[o["c"]] = o
    except (OSError, ValueError) as err:
        log(f"::warning::Outlet master not read ({err}); outlets will show as not in the outlet master.")

    rng = snap.get("range") or {}
    days = rng.get("days") or 0
    outlets, unmapped = [], []
    for o in snap["outlets"]:
        code = str(o.get("OutletCode") or "").strip()
        if not code:
            continue
        m = master.get(code)
        if not m:
            unmapped.append(code)
        name = str(o.get("Outlet") or code)
        if name.startswith(code):
            name = name[len(code):].lstrip(" -")
        row = {"c": code, "n": (m or {}).get("n") or name or code, "region": o.get("Region"),
               "r": num(o.get("Receiving")), "s": num(o.get("Sales")), "inv": num(o.get("Inventory")),
               "ov": num(o.get("OverValue"), 0), "oi": o.get("OverIncidents") or 0, "ui": o.get("UnderIncidents") or 0}
        for k in DIMS:
            row[k] = (m or {}).get(k)
        outlets.append(row)

    def agg(rows, key):
        return [{"k": x.get(key) or "Not set", "r": num(x.get("Receiving")), "s": num(x.get("Sales")), "inv": num(x.get("Inventory")),
                 "ov": num(x.get("OverValue"), 0), "oi": x.get("OverIncidents") or 0, "ui": x.get("UnderIncidents") or 0} for x in rows or []]

    k = snap["kpis"][0]
    payload = {
        "schema": 1,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {"snapshot": SNAPSHOT_URL, "report": snap.get("sourceReport"), "powerBiRefreshedAt": snap.get("sourceTimestamp"),
                   "snapshotAt": snap.get("snapshotGeneratedAt"), "divisions": (snap.get("scope") or {}).get("masterCategories") or [],
                   "movementTypes": (snap.get("scope") or {}).get("movementTypes") or []},
        "range": {"start": rng.get("start"), "end": (dt.date.fromisoformat(rng["endExclusive"]) - dt.timedelta(days=1)).isoformat() if rng.get("endExclusive") else None, "days": days},
        "kpis": {"r": num(k.get("Receiving")), "s": num(k.get("Sales")), "inv": num(k.get("Inventory")), "stock": num(k.get("LatestStock")),
                 "sd": num(k.get("StockDay")), "ov": num(k.get("OverValue"), 0), "oi": k.get("OverIncidents") or 0, "ui": k.get("UnderIncidents") or 0,
                 "oiPct": num(k.get("OverIncidentPct")), "uiPct": num(k.get("UnderIncidentPct")), "outlets": k.get("ActiveOutlets") or len(outlets)},
        "trend": [{"d": dt.datetime.fromtimestamp(t["Date"] / 1000, dt.timezone.utc).date().isoformat(), "r": num(t.get("Receiving")), "s": num(t.get("Sales"))}
                  for t in snap.get("trend") or [] if isinstance(t.get("Date"), (int, float))],
        "categories": agg(snap.get("categories"), "Category"),
        "regions": agg(snap.get("regions"), "Region"),
        "outlets": outlets,
        # Article rows: [code, name, category, received, sold]; only articles with movement in the window.
        "articles": [[a.get("ArticleNo"), a.get("ArticleName"), a.get("Category"), num(a.get("Receiving")), num(a.get("Sales"))]
                     for a in snap.get("articleOptions") or [] if a.get("Receiving") or a.get("Sales")],
        "quality": {"outlets": len(outlets), "unmapped": sorted(unmapped)},
    }

    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        if {k: v for k, v in old.items() if k != "generatedAt"} == {k: v for k, v in payload.items() if k != "generatedAt"}:
            log("No receiving changes; rcv.json left as is.")
            return 0
    except (OSError, ValueError):
        pass
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT)
    log(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(outlets)} outlets ({len(unmapped)} not in the outlet master), "
        f"{len(payload['articles'])} articles, {payload['range']['start']} to {payload['range']['end']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
