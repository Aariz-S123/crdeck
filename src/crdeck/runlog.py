"""Machine-readable run log (data/processed/run_log.json).

Each pipeline stage records what it actually did, so the website's "Model log" shows only
recorded facts: build (data counts), evaluate:<mode> (splits, model selection, test metrics),
export (code version, configs, timestamps). Nothing here is typed by hand.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import PROJECT_ROOT, Paths


def _jsonable(x: Any) -> Any:
    if isinstance(x, pd.DataFrame):
        return x.to_dict("records")
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if hasattr(x, "item"):  # numpy scalars
        return x.item()
    return x


def log_path(paths: Paths) -> Path:
    return paths.processed / "run_log.json"


def read(paths: Paths) -> dict:
    p = log_path(paths)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def write_section(paths: Paths, section: str, data: dict) -> None:
    log = read(paths)
    log[section] = {**_jsonable(data), "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    paths.processed.mkdir(parents=True, exist_ok=True)
    with log_path(paths).open("w", encoding="utf-8") as f:
        json.dump(log, f, indent=1, default=str)


def git_version() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {"commit": run("rev-parse", "HEAD"), "commit_date": run("log", "-1", "--format=%cI"),
            "uncommitted_changes": bool(run("status", "--porcelain", "--untracked-files=no"))}


def build_section(paths: Paths, counts: dict) -> dict:
    """Collection windows and fetch times from data/raw_manifest.csv, plus the build counts."""
    manifest = paths.root / "raw_manifest.csv"
    windows = []
    if manifest.exists():
        m = pd.read_csv(manifest)
        for w, g in m.groupby("window_id"):
            windows.append({"window_id": w, "files": int(len(g)), "battle_logs": int((g["kind"] == "battlelog").sum()),
                            "http_status": {str(k): int(v) for k, v in g["status"].value_counts().items()},
                            "first_fetch": str(g["fetched_at"].min()), "last_fetch": str(g["fetched_at"].max())})
    keep = ("files", "files_without_battles", "battle_rows_before_dedupe", "battles_after_dedupe", "duplicates_removed",
            "status", "modes", "ok_by_mode_arena", "unknown_card_ids", "distinct_decks", "first_battle", "last_battle",
            "card_table_rows", "card_attach_report")
    return {"windows": windows, **{k: counts[k] for k in keep if k in counts}}


def model_notes_caveats() -> dict:
    """docs/model-notes.md sections, verbatim, keyed by heading."""
    text = (PROJECT_ROOT / "docs" / "model-notes.md").read_text(encoding="utf-8")
    sections, cur, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur:
                sections[cur] = "\n".join(buf).strip()
            cur, buf = line[3:].strip(), []
        elif cur:
            buf.append(line)
    if cur:
        sections[cur] = "\n".join(buf).strip()
    return sections
