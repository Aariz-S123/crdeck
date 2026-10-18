"""Restart-and-run-all check for every notebook (spec 9.1).

Runs each notebook in a fresh kernel with CRDECK_DATA_SOURCE taken from the
environment (default "real"). Executed copies go to <data root>/notebooks_out/
(git-ignored); the committed notebooks stay output-free. Exit code 1 if any fails.

    CRDECK_DATA_SOURCE=synthetic python scripts/run_notebooks.py
    python scripts/run_notebooks.py 07_demo.ipynb
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from crdeck.config import Paths  # noqa: E402


def main(argv: list[str]) -> int:
    paths = Paths.for_source(None)
    out_dir = paths.root / "notebooks_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    names = argv or sorted(p.name for p in (ROOT / "notebooks").glob("*.ipynb"))
    print(paths.banner())
    failed = []
    for name in names:
        nb = nbformat.read(ROOT / "notebooks" / name, as_version=4)
        t = time.time()
        try:
            NotebookClient(nb, timeout=900, kernel_name="python3", resources={"metadata": {"path": str(ROOT / "notebooks")}}).execute()
            status = "ok"
        except CellExecutionError as e:
            status = "FAILED: " + str(e).strip().splitlines()[-1][:300]
            failed.append(name)
        nbformat.write(nb, out_dir / name)
        print(f"{name:22s} {status} ({time.time() - t:.0f}s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
