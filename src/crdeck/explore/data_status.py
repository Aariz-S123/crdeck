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


def _iso(t: str | None) -> str | None:
    """'2026-10-27 01:15 UTC', '2026-10-27 01:22:09+00:00' or ISO, as '2026-10-27T01:15:00Z'; None stays None."""
    if not t:
        return None
    s = str(t).strip().replace(" UTC", "+00:00")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_site(web: Path) -> dict[str, dict]:
    """Each key's dates read from the files the site already serves, so no export has to be rerun:
    models from modes.json (and the Ranked model's newest battle), future_meta from future_meta.json, balance_watch
    from balance_watch.json. A file that is missing gives no key."""
    web = Path(web)
    out: dict[str, dict] = {}
    modes = web / "modes.json"
    if modes.exists():
        index = json.loads(modes.read_text(encoding="utf-8"))
        main = next((m for m in index.get("modes", []) if m.get("slug") == index.get("default") and m.get("status") == "exported"), None)
        last = None
        if main and (web / main["file"]).exists():
            with (web / main["file"]).open(encoding="utf-8") as f:
                last = ((json.load(f).get("meta") or {}).get("counts") or {}).get("last_battle")
        out["models"] = {"last_battle": _iso(last),
                         "trained_from": _iso((main or {}).get("train_window", [None])[0]),
                         "tested_to": _iso(((main or {}).get("test_window") or [None, None])[1]),
                         "exported": _iso(((index.get("log") or {}).get("export") or {}).get("exported_at"))}
    fm = web / "future_meta.json"
    if fm.exists():
        body = json.loads(fm.read_text(encoding="utf-8"))
        periods = (body.get("data") or {}).get("periods") or []
        out["future_meta"] = {"last_period_end": _iso(periods[-1]["end"]) if periods else None, "periods": len(periods),
                              "exported": _iso(body.get("written_at"))}
    bw = web / "balance_watch.json"
    if bw.exists():
        body = json.loads(bw.read_text(encoding="utf-8"))
        out["balance_watch"] = {"cutoff": body.get("cutoff"), "window_start": (body.get("window") or {}).get("start"), "status": body.get("status"),
                                "last_update": ((body.get("calendar") or {}).get("last_event") or {}).get("effective_date"),
                                "exported": body.get("generated_at")}
    return out


def refresh(web: Path) -> dict:
    """Rewrite every key from the site's own files (see from_site). `written` is each file's own export time."""
    body = read(web)
    for key, value in from_site(web).items():
        body[key] = {**value, "written": value.get("exported")}
    ordered = {k: body[k] for k in KEYS if k in body}
    (Path(web) / FILE_NAME).write_text(json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ordered


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
