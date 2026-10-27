"""Write a dashboard data file only when its contents changed.

Every build stamps its output with the time it ran (generatedAt, generated, syncedAt). Rewriting a file
whose only change is that stamp makes the refresh commit and redeploy it, and makes every browser download
it again. write_json compares the new payload with the file on disk, ignoring those stamps at any depth,
and leaves the file (and its modified time) untouched when nothing else differs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

RUN_STAMPS = frozenset({"generatedAt", "generated", "syncedAt"})


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in RUN_STAMPS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def write_json(path, payload, *, ensure_ascii: bool = False, separators=(",", ":"), **dump_kw) -> bool:
    """Atomically write payload as JSON unless only its run stamps changed. Returns True when written."""
    path = Path(path)
    text = json.dumps(payload, ensure_ascii=ensure_ascii, separators=separators, **dump_kw)
    try:
        if _strip(json.loads(path.read_text(encoding="utf-8"))) == _strip(json.loads(text)):
            print(f"No data changes; {path.name} left as is.", flush=True)
            return False
    except (OSError, ValueError):
        pass  # no previous file, or an unreadable one: write it
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o644)
    os.replace(tmp, path)  # atomic: visitors never see a half-written file
    return True
