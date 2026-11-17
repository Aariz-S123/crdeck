"""Rewrite web/data_status.json from the files the site already serves (no export is rerun).

    python scripts/data_status.py

Run after scripts/export_web.py (which calls it itself), scripts/future_meta.py or scripts/balance_watch.py. Every
page's footer reads the file and says how fresh each part of the site's data is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crdeck.explore import data_status  # noqa: E402


def main() -> int:
    body = data_status.refresh(ROOT / "web")
    print(json.dumps(body, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
