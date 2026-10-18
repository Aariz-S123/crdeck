"""Restart-and-run-all check for every notebook (spec 9.1, and the section 10 case
"re-running a notebook gives the same outputs").

Runs each notebook in a fresh kernel with CRDECK_DATA_SOURCE taken from the
environment (default "real"). Executed copies go to <data root>/notebooks_out/
(git-ignored); the committed notebooks stay output-free. Exit code 1 if any fails.

    CRDECK_DATA_SOURCE=synthetic python scripts/run_notebooks.py
    CRDECK_DATA_SOURCE=synthetic python scripts/run_notebooks.py --twice   # determinism check
    python scripts/run_notebooks.py 07_demo.ipynb

--twice runs every notebook in two fresh kernels with the model cache disabled
(CRDECK_NO_CACHE=1), so models are retrained each time, and compares all outputs.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from crdeck.config import Paths  # noqa: E402

# Output fragments that legitimately change between runs.
VOLATILE = [re.compile(r"\d+(\.\d+)?s\b"), re.compile(r"0x[0-9a-f]+")]


def execute(name: str) -> tuple[nbformat.NotebookNode, str]:
    nb = nbformat.read(ROOT / "notebooks" / name, as_version=4)
    try:
        NotebookClient(nb, timeout=900, kernel_name="python3",
                       resources={"metadata": {"path": str(ROOT / "notebooks")}}).execute()
        return nb, "ok"
    except CellExecutionError as e:
        return nb, "FAILED: " + str(e).strip().splitlines()[-1][:300]


def outputs(nb) -> list[str]:
    out = []
    for i, c in enumerate(nb.cells):
        if c.cell_type != "code":
            continue
        for o in c.get("outputs", []):
            txt = o.get("text") or o.get("data", {}).get("text/plain", "") or o.get("evalue", "")
            for v in VOLATILE:
                txt = v.sub("<v>", str(txt))
            out.append(f"[cell {i}] {txt}")
    return out


def main(argv: list[str]) -> int:
    twice = "--twice" in argv
    names = [a for a in argv if not a.startswith("--")]
    if twice:
        os.environ["CRDECK_NO_CACHE"] = "1"
    paths = Paths.for_source(None)
    out_dir = paths.root / "notebooks_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    names = names or sorted(p.name for p in (ROOT / "notebooks").glob("*.ipynb"))
    print(paths.banner())
    failed = []
    for name in names:
        t = time.time()
        nb, status = execute(name)
        nbformat.write(nb, out_dir / name)
        if twice and status == "ok":
            nb2, status2 = execute(name)
            if status2 != "ok":
                status = "second run " + status2
            else:
                a, b = outputs(nb), outputs(nb2)
                diff = [(x, y) for x, y in zip(a, b) if x != y]
                if diff or len(a) != len(b):
                    first = diff[0] if diff else ("<different output count>", "")
                    status = f"NOT DETERMINISTIC ({len(diff)} outputs differ); first: {first[0][:120]!r} vs {first[1][:120]!r}"
                else:
                    status = f"ok, identical across 2 runs ({len(a)} outputs)"
        if not status.startswith("ok"):
            failed.append(name)
        print(f"{name:22s} {status} ({time.time() - t:.0f}s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
