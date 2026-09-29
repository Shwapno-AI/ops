#!/usr/bin/env python3
"""Has anything changed in the dashboard's Google Drive folders since the last check?

Lists the folders the refresh scripts read (names and last-modified times only, nothing is
downloaded) and compares them with the previous listing. deploy/entrypoint.sh runs this every
few minutes and starts a refresh as soon as a file is added, replaced, renamed or removed.

Exit status: 0 = something changed (the changes are printed), 1 = nothing changed,
2 = the folders could not be listed. The first run only records the listing (exit 1).

Usage: python scripts/watch_drive.py            # compare and remember the new listing
       python scripts/watch_drive.py --baseline # just remember the current listing
Environment: DATA_FOLDER_ID, NETWORK_FOLDER_ID, CW_FOLDER_ID, AV_FOLDER_ID, SKU_FOLDER_ID (the same
overrides the refresh scripts use), WATCH_STATE (default /tmp/drive-watch.json).
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "network"))
import fetch_drive_data as drive  # noqa: E402

MOTHER = "1Te9stxbcBsIIO8bNElPuDXXPovkk4v1l"
SKU = "111qtlTIgOpvuYK7G4B_xrA8hRBpwjcj_"
SA = "1TJ_c7VVyg6Qa_o0c62_LsZkd0sBHDEHF"  # Store Assessment audit exports
STATE = Path(os.environ.get("WATCH_STATE") or "/tmp/drive-watch.json")


def folders():
    env = lambda k: (os.environ.get(k) or "").strip()  # noqa: E731
    data = env("DATA_FOLDER_ID") or MOTHER
    return sorted({data, env("NETWORK_FOLDER_ID") or data, env("CW_FOLDER_ID") or data, env("AV_FOLDER_ID") or data, env("SKU_FOLDER_ID") or SKU, env("SA_FOLDER_ID") or SA})


def listing():
    out = {}
    for folder in folders():
        for item in drive.walk(folder):
            out[item["id"]] = [item.get("path") or item["name"], item.get("modified", "")]
    return out


def main():
    try:
        now = listing()
    except Exception as err:  # noqa: BLE001 - network or sharing problem; the hourly refresh still runs
        print(f"Drive watch: could not list the folders ({err})")
        return 2
    try:
        before = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before = None
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(now), encoding="utf-8")
    if before is None or "--baseline" in sys.argv:
        return 1
    changes = []
    for fid, (name, mod) in now.items():
        if fid not in before:
            changes.append(f"added {name}")
        elif before[fid] != [name, mod]:
            changes.append(f"changed {name} ({before[fid][1]} -> {mod})" if before[fid][0] == name else f"renamed {before[fid][0]} -> {name}")
    changes += [f"removed {before[fid][0]}" for fid in before if fid not in now]
    if not changes:
        return 1
    print(f"Drive watch: {len(changes)} change(s): " + "; ".join(changes[:10]) + (" …" if len(changes) > 10 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
