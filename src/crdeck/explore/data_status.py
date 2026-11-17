"""web/data_status.json: one place that says how fresh each part of the site's data is.

The site's pages are built by different scripts on different days (the model export, the future-meta forecast, the
balance watch). Each script writes its own key here and leaves the others alone, and every page's footer reads the
file, so the whole site states its data dates the same way.

    {"models": {...}, "future_meta": {...}, "balance_watch": {...}}

Every value is a small dict of ISO dates and times in UTC; `written` is when that script last ran.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

FILE_NAME = "data_status.json"
KEYS = ("models", "future_meta", "balance_watch")


def read(web: Path) -> dict:
    f = Path(web) / FILE_NAME
    if not f.exists():
        return {}
    try:
        body = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


def update(web: Path, key: str, value: dict, written: str | None = None) -> dict:
    """Set one key, keep the others, write the file back. Returns the whole body."""
    if key not in KEYS:
        raise ValueError(f"unknown data-status key {key!r}; expected one of {KEYS}")
    body = read(web)
    body[key] = {**value, "written": written or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    ordered = {k: body[k] for k in KEYS if k in body}
    (Path(web) / FILE_NAME).write_text(json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ordered
